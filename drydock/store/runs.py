"""Runs, run_events, workspaces, audit, asks, policy_grants — the runtime's store.

Kept separate from the PM store (service.py) because these are written on the hot
path by the toolbus/session and read by the server SSE layer.
"""
from __future__ import annotations

from . import db, service
from .db import dumps, load_row, now, ulid


# ── runs ────────────────────────────────────────────────────────────────────

def create_run(project, agent_id=None, ticket_id=None, work_item_id=None,
               runner="native", tier=0, model=None) -> dict:
    pid = service._pid(project)
    rid = ulid()
    db.execute(
        """INSERT INTO runs(id, project_id, agent_id, ticket_id, work_item_id,
                            runner, tier, model, status, started_at)
           VALUES (?,?,?,?,?,?,?,?, 'queued', ?)""",
        (rid, pid, agent_id, ticket_id, work_item_id, runner, int(tier), model, now()),
    )
    return db.one("SELECT * FROM runs WHERE id=?", (rid,))


def set_run_status(run_id, status, summary=None) -> None:
    sets = ["status=?"]
    params = [status]
    if status in ("done", "failed", "killed"):
        sets.append("ended_at=?")
        params.append(now())
    if summary is not None:
        sets.append("summary=?")
        params.append(summary)
    params.append(run_id)
    db.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id=?", params)


def add_run_tokens(run_id, tokens_in=0, tokens_out=0, cost_cents=0) -> None:
    db.execute(
        "UPDATE runs SET tokens_in=tokens_in+?, tokens_out=tokens_out+?, "
        "cost_cents=cost_cents+? WHERE id=?",
        (int(tokens_in), int(tokens_out), int(cost_cents), run_id))


def set_run_workspace(run_id, workspace_id) -> None:
    db.execute("UPDATE runs SET workspace_id=? WHERE id=?", (workspace_id, run_id))


def get_run(run_id) -> dict | None:
    return db.one("SELECT * FROM runs WHERE id=?", (run_id,))


def list_runs(project, status=None, limit=50) -> list[dict]:
    pid = service._pid(project)
    sql, params = "SELECT * FROM runs WHERE project_id=?", [pid]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    return db.q(sql, params)


# ── run_events (transcript + SSE source) ────────────────────────────────────

def add_event(run_id, type, payload: dict) -> dict:
    row = db.one("SELECT COALESCE(MAX(seq), 0) AS m FROM run_events WHERE run_id=?", (run_id,))
    seq = (row["m"] or 0) + 1
    eid = ulid()
    db.execute(
        "INSERT INTO run_events(id, run_id, seq, type, payload_json, ts) VALUES (?,?,?,?,?,?)",
        (eid, run_id, seq, type, dumps(payload), now()))
    return {"id": eid, "run_id": run_id, "seq": seq, "type": type,
            "payload": payload, "ts": now()}


def get_events(run_id, after_seq=0) -> list[dict]:
    rows = db.q(
        "SELECT * FROM run_events WHERE run_id=? AND seq>? ORDER BY seq",
        (run_id, after_seq))
    return [load_row(r, ("payload",)) for r in rows]


# ── workspaces ──────────────────────────────────────────────────────────────

def create_workspace(project, run_id=None, tier=0, kind="worktree", path=None,
                     wsl_distro=None, container_id=None, base_commit=None,
                     branch=None) -> dict:
    pid = service._pid(project)
    wid = ulid()
    db.execute(
        """INSERT INTO workspaces(id, project_id, run_id, tier, kind, path, wsl_distro,
                                  container_id, base_commit, branch, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?, 'active', ?)""",
        (wid, pid, run_id, int(tier), kind, path, wsl_distro, container_id,
         base_commit, branch, now()))
    return db.one("SELECT * FROM workspaces WHERE id=?", (wid,))


def set_workspace_status(workspace_id, status) -> None:
    db.execute("UPDATE workspaces SET status=? WHERE id=?", (status, workspace_id))


def get_workspace(workspace_id) -> dict | None:
    return db.one("SELECT * FROM workspaces WHERE id=?", (workspace_id,))


# ── audit (native runs + external hook events) ──────────────────────────────

def add_audit(decision, event=None, tool=None, action=None, rule=None,
              message=None, args=None, identity=None, run_id=None,
              ext_session_id=None, tokens=None) -> dict:
    aid = ulid()
    db.execute(
        """INSERT INTO audit(id, run_id, ext_session_id, ts, event, tool, action,
                             decision, rule, message, args_json, identity, tokens_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (aid, run_id, ext_session_id, now(), event, tool, action, decision, rule,
         message, dumps(args or {}), identity, dumps(tokens) if tokens else None))
    return db.one("SELECT * FROM audit WHERE id=?", (aid,))


def list_audit(project=None, run_id=None, decision=None, agent=None, tool=None,
               source=None, limit=200) -> list[dict]:
    where, params = [], []
    if run_id:
        where.append("a.run_id=?")
        params.append(run_id)
    if project:
        pid = service._pid(project)
        where.append("(a.run_id IN (SELECT id FROM runs WHERE project_id=?) OR a.run_id IS NULL)")
        params.append(pid)
    if decision:
        where.append("a.decision=?")
        params.append(decision)
    if agent:
        where.append("a.identity LIKE ?")
        params.append(agent + "%")
    if tool:
        where.append("a.tool=?")
        params.append(tool)
    if source == "external":
        where.append("a.ext_session_id IS NOT NULL")
    elif source == "native":
        where.append("a.ext_session_id IS NULL")
    sql = "SELECT a.* FROM audit a"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY a.ts DESC LIMIT ?"
    params.append(limit)
    return db.q(sql, params)


# ── asks (human-in-the-loop) ────────────────────────────────────────────────

def create_ask(run_id, audit_id, expires_at=None) -> dict:
    aid = ulid()
    db.execute(
        "INSERT INTO asks(id, run_id, audit_id, status, expires_at, created_at) "
        "VALUES (?,?,?, 'pending', ?, ?)",
        (aid, run_id, audit_id, expires_at, now()))
    return db.one("SELECT * FROM asks WHERE id=?", (aid,))


def get_ask(ask_id) -> dict | None:
    return db.one("SELECT * FROM asks WHERE id=?", (ask_id,))


def list_asks(status="pending", project=None) -> list[dict]:
    sql, params = "SELECT * FROM asks WHERE status=?", [status]
    if project:
        pid = service._pid(project)
        sql += " AND run_id IN (SELECT id FROM runs WHERE project_id=?)"
        params.append(pid)
    sql += " ORDER BY created_at"
    return db.q(sql, params)


def resolve_ask(ask_id, status, resolved_by=None) -> dict | None:
    """status: approved_once | always | denied | expired."""
    db.execute(
        "UPDATE asks SET status=?, resolved_by=?, resolved_at=? WHERE id=? AND status='pending'",
        (status, resolved_by, now(), ask_id))
    return get_ask(ask_id)


# ── policy grants (persisted "always allow") ────────────────────────────────

def add_grant(project, rule, scope=None, agent_id=None, created_by=None) -> dict:
    pid = service._pid(project)
    gid = ulid()
    db.execute(
        "INSERT INTO policy_grants(id, project_id, agent_id, rule, scope_json, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (gid, pid, agent_id, rule, dumps(scope or {}), created_by, now()))
    return db.one("SELECT * FROM policy_grants WHERE id=?", (gid,))


def list_grants(project, agent_id=None) -> list[dict]:
    pid = service._pid(project)
    sql, params = "SELECT * FROM policy_grants WHERE project_id=?", [pid]
    if agent_id:
        sql += " AND (agent_id=? OR agent_id IS NULL)"
        params.append(agent_id)
    return [load_row(r, ("scope",)) for r in db.q(sql, params)]
