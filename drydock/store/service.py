"""Core store API — port of orbit ``pmhub_core/service.py`` to SQLite.

Same public contract (function names, arg shapes, returned dicts) so orbit's MCP
tool surface carries over. Differences:
  - SQLite + FTS5 instead of Postgres + tsvector
  - vectors are optional; ``search_context`` is FTS-first and merges the vector
    leg via RRF when the ``vectors`` extra is installed (see fts.py)
  - embeds never block a write (orbit's defer_embed lesson is the default here)
"""
from __future__ import annotations

import re

from . import db
from .db import dumps, load_row, loads, now, ulid


# ── projects ────────────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-") or "project"


def create_project(name, root_path=None, git_remote=None, description=None,
                   slug=None, ticket_prefix=None) -> dict:
    slug = slug or _slugify(name)
    prefix = (ticket_prefix or "".join(
        w[0] for w in re.findall(r"[A-Za-z]+", name)[:3]).upper() or "TCK")[:6]
    pid = ulid()
    db.execute(
        """INSERT INTO projects(id, slug, name, description, root_path, git_remote,
                                ticket_prefix, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (pid, slug, name, description, root_path, git_remote, prefix, now()),
    )
    if root_path:
        add_repo(slug, root_path, name=None, git_remote=git_remote, is_primary=True)
    return get_project(slug)


def get_project(ref) -> dict | None:
    return db.one(
        "SELECT * FROM projects WHERE slug=? OR id=? OR name=?", (ref, ref, ref))


def list_projects() -> list[dict]:
    return db.q("SELECT * FROM projects ORDER BY created_at DESC")


def _pid(ref) -> str:
    p = get_project(ref)
    if not p:
        raise ValueError(f"unknown project: {ref!r}")
    return p["id"]


# ── repos ───────────────────────────────────────────────────────────────────

def add_repo(project, root_path, name=None, git_remote=None, is_primary=False) -> dict:
    pid = _pid(project)
    rid = ulid()
    rname = name or root_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if is_primary:
        db.execute("UPDATE repos SET is_primary=0 WHERE project_id=?", (pid,))
    db.execute(
        "INSERT INTO repos(id, project_id, path, name, git_remote, is_primary, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (rid, pid, root_path, rname, git_remote, int(is_primary), now()),
    )
    return db.one("SELECT * FROM repos WHERE id=?", (rid,))


def list_repos(project) -> list[dict]:
    pid = _pid(project)
    return db.q("SELECT * FROM repos WHERE project_id=? ORDER BY is_primary DESC, created_at", (pid,))


def resolve_repo(project, repo=None) -> dict | None:
    """Named repo, else the primary, else the only repo."""
    rows = list_repos(project)
    if not rows:
        return None
    if repo:
        for r in rows:
            if r["name"] == repo or r["id"] == repo or r["path"] == repo:
                return r
        return None
    return rows[0]


# ── memories ────────────────────────────────────────────────────────────────

def add_memory(project, body, title=None, kind="episodic", tags=None,
               source=None, source_trust="inferred", importance=0.5,
               pinned=False, defer_embed=True) -> dict:
    pid = _pid(project)
    mid = ulid()
    db.execute(
        """INSERT INTO memories(id, project_id, kind, title, body, tags_json, source,
                                source_trust, importance, pinned, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (mid, pid, kind, title, body, dumps(tags or []), source,
         source_trust, float(importance), int(bool(pinned)), now()),
    )
    # embedding is best-effort and never blocks the write
    if not defer_embed:
        from . import fts
        fts.embed_memory(mid)
    return load_row(db.one("SELECT * FROM memories WHERE id=?", (mid,)), ("tags",))


def pin(memory_id, pinned=True) -> dict | None:
    db.execute("UPDATE memories SET pinned=? WHERE id=?", (int(bool(pinned)), memory_id))
    return load_row(db.one("SELECT * FROM memories WHERE id=?", (memory_id,)), ("tags",))


def search_context(project, query, k=5, kind=None, tags=None) -> list[dict]:
    """Hybrid recall over memories. FTS5 always; vector leg merged when available."""
    from . import fts
    return fts.search_memories(project, query, k=k, kind=kind, tags=tags)


# ── decisions ───────────────────────────────────────────────────────────────

def log_decision(project, title, rationale=None, alternatives=None,
                 supersedes=None, ticket_id=None) -> dict:
    pid = _pid(project)
    did = ulid()
    if supersedes:
        db.execute(
            "UPDATE decisions SET status='superseded' WHERE id=? AND project_id=?",
            (supersedes, pid),
        )
    db.execute(
        """INSERT INTO decisions(id, project_id, title, rationale, alternatives_json,
                                 supersedes_id, ticket_id, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (did, pid, title, rationale, dumps(alternatives or []), supersedes, ticket_id, now()),
    )
    return load_row(db.one("SELECT * FROM decisions WHERE id=?", (did,)), ("alternatives",))


def get_decisions(project, active_only=True) -> list[dict]:
    pid = _pid(project)
    sql = "SELECT * FROM decisions WHERE project_id=?"
    if active_only:
        sql += " AND status='active'"
    sql += " ORDER BY created_at DESC"
    return [load_row(r, ("alternatives",)) for r in db.q(sql, (pid,))]


# ── work items ──────────────────────────────────────────────────────────────

def create_work_item(project, title, type="task", body=None, status="open",
                     priority=2, ticket_id=None) -> dict:
    pid = _pid(project)
    wid = ulid()
    ts = now()
    db.execute(
        """INSERT INTO work_items(id, project_id, ticket_id, type, title, body,
                                  status, priority, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (wid, pid, ticket_id, type, title, body, status, int(priority), ts, ts),
    )
    return db.one("SELECT * FROM work_items WHERE id=?", (wid,))


def update_work_item(id, status=None, priority=None, title=None, body=None) -> dict | None:
    sets, params = [], []
    for col, val in (("status", status), ("priority", priority),
                     ("title", title), ("body", body)):
        if val is not None:
            sets.append(f"{col}=?")
            params.append(val)
    if not sets:
        return db.one("SELECT * FROM work_items WHERE id=?", (id,))
    sets.append("updated_at=?")
    params.extend([now(), id])
    db.execute(f"UPDATE work_items SET {', '.join(sets)} WHERE id=?", params)
    return db.one("SELECT * FROM work_items WHERE id=?", (id,))


def list_work_items(project, status=None, ticket_id=None) -> list[dict]:
    pid = _pid(project)
    sql, params = "SELECT * FROM work_items WHERE project_id=?", [pid]
    if status:
        sql += " AND status=?"
        params.append(status)
    if ticket_id:
        sql += " AND ticket_id=?"
        params.append(ticket_id)
    sql += " ORDER BY priority, updated_at DESC"
    return db.q(sql, params)


# ── handoffs ────────────────────────────────────────────────────────────────

def create_handoff(project, summary=None, current_state=None, next_steps=None,
                   blockers=None, run_id=None) -> dict:
    pid = _pid(project)
    # a new handoff consumes the previous active one
    db.execute(
        "UPDATE handoffs SET status='consumed', updated_at=? WHERE project_id=? AND status='active'",
        (now(), pid),
    )
    hid = ulid()
    ts = now()
    db.execute(
        """INSERT INTO handoffs(id, project_id, summary, current_state, next_steps_json,
                                blockers_json, run_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (hid, pid, summary, current_state, dumps(next_steps or []),
         dumps(blockers or []), run_id, ts, ts),
    )
    return load_row(db.one("SELECT * FROM handoffs WHERE id=?", (hid,)),
                    ("next_steps", "blockers"))


def get_handoff(project) -> dict | None:
    pid = _pid(project)
    row = db.one(
        "SELECT * FROM handoffs WHERE project_id=? AND status='active' "
        "ORDER BY created_at DESC LIMIT 1", (pid,))
    return load_row(row, ("next_steps", "blockers"))


# ── attempts ────────────────────────────────────────────────────────────────

def log_attempt(project, what_tried, outcome, why=None, work_item_id=None) -> dict:
    pid = _pid(project)
    aid = ulid()
    db.execute(
        "INSERT INTO attempts(id, project_id, work_item_id, what_tried, outcome, why, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (aid, pid, work_item_id, what_tried, outcome, why, now()),
    )
    return db.one("SELECT * FROM attempts WHERE id=?", (aid,))


def get_attempts(project, work_item_id=None) -> list[dict]:
    pid = _pid(project)
    sql, params = "SELECT * FROM attempts WHERE project_id=?", [pid]
    if work_item_id:
        sql += " AND work_item_id=?"
        params.append(work_item_id)
    sql += " ORDER BY created_at DESC"
    return db.q(sql, params)


# ── graph ───────────────────────────────────────────────────────────────────

def relate(project, src_type, src_id, dst_type, dst_id, relation) -> dict:
    from .graph_links import _add_edge
    pid = _pid(project)
    added = _add_edge(pid, src_type, src_id, dst_type, dst_id, relation)
    return {"added": bool(added), "relation": relation}


def get_related(project, entity_name, depth=1) -> dict:
    """Edges touching a named entity (depth 1: direct neighbors)."""
    pid = _pid(project)
    ent = db.one(
        "SELECT * FROM entities WHERE project_id=? AND name=?", (pid, entity_name))
    if not ent:
        return {"entity": entity_name, "found": False, "neighbors": []}
    eid = ent["id"]
    rows = db.q(
        """SELECT src_type, src_id, dst_type, dst_id, relation, weight
           FROM relationships
           WHERE project_id=? AND valid_to IS NULL
             AND ((dst_type='entity' AND dst_id=?) OR (src_type='entity' AND src_id=?))""",
        (pid, eid, eid),
    )
    return {"entity": entity_name, "found": True, "kind": ent["kind"], "neighbors": rows}


# ── resume ──────────────────────────────────────────────────────────────────

def resume(project, token_budget=2000, include_context=True) -> dict:
    """Session-start packet: project + handoff + active decisions + budget-packed context."""
    from . import allocator
    p = get_project(project)
    if not p:
        raise ValueError(f"unknown project: {project!r}")
    out = {
        "project": {k: p[k] for k in ("id", "slug", "name", "root_path", "ticket_prefix")},
        "handoff": get_handoff(project),
        "active_decisions": get_decisions(project, active_only=True)[:10],
        "open_work": list_work_items(project, status="open")[:15],
    }
    if include_context:
        out["context"] = allocator.assemble(project, token_budget=token_budget)
    return out
