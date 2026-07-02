"""Agent/skill registry — port of orbit ``registry.py`` (upsert-by-name, versioned)."""
from __future__ import annotations

from . import db, service
from .db import dumps, load_row, now, ulid


def _agent_row(row):
    return load_row(load_row(row, ("tools",)), ("definition",))


# ── agents ──────────────────────────────────────────────────────────────────

def register_agent(project, name, description=None, definition=None, model=None,
                   tools=None, definition_md=None, policy_yaml=None) -> dict:
    pid = service._pid(project) if project else None
    existing = db.one(
        "SELECT id, version FROM agents WHERE project_id IS ? AND name=?", (pid, name))
    ts = now()
    if existing:
        db.execute(
            """UPDATE agents SET description=?, definition_json=?, model=?, tools_json=?,
                                 definition_md=COALESCE(?, definition_md),
                                 policy_yaml=COALESCE(?, policy_yaml),
                                 version=version+1, updated_at=?
               WHERE id=?""",
            (description, dumps(definition or {}), model, dumps(tools or []),
             definition_md, policy_yaml, ts, existing["id"]))
        aid = existing["id"]
    else:
        aid = ulid()
        db.execute(
            """INSERT INTO agents(id, project_id, name, description, definition_md,
                                  definition_json, model, tools_json, policy_yaml,
                                  created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, pid, name, description, definition_md, dumps(definition or {}),
             model, dumps(tools or []), policy_yaml, ts, ts))
    return _agent_row(db.one("SELECT * FROM agents WHERE id=?", (aid,)))


def list_agents(project) -> list[dict]:
    pid = service._pid(project) if project else None
    return [_agent_row(r) for r in db.q(
        "SELECT * FROM agents WHERE project_id IS ? OR project_id IS NULL "
        "ORDER BY created_at DESC", (pid,))]


def get_agent(project, name_or_id) -> dict | None:
    pid = service._pid(project) if project else None
    row = db.one(
        "SELECT * FROM agents WHERE (project_id IS ? OR project_id IS NULL) "
        "AND (name=? OR id=?) ORDER BY project_id IS NULL LIMIT 1",
        (pid, name_or_id, name_or_id))
    return _agent_row(row)


# ── skills ──────────────────────────────────────────────────────────────────

def register_skill(project, name, description=None, body=None, steps=None,
                   level="skill") -> dict:
    pid = service._pid(project)
    existing = db.one(
        "SELECT id FROM skills WHERE project_id=? AND name=?", (pid, name))
    ts = now()
    if existing:
        db.execute(
            "UPDATE skills SET description=?, body=?, steps_json=?, level=?, updated_at=? WHERE id=?",
            (description, body, dumps(steps or []), level, ts, existing["id"]))
        sid = existing["id"]
    else:
        sid = ulid()
        db.execute(
            """INSERT INTO skills(id, project_id, name, description, body, steps_json,
                                  level, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (sid, pid, name, description, body, dumps(steps or []), level, ts, ts))
    return load_row(db.one("SELECT * FROM skills WHERE id=?", (sid,)), ("steps",))


def list_skills(project) -> list[dict]:
    pid = service._pid(project)
    return [load_row(r, ("steps",)) for r in db.q(
        "SELECT * FROM skills WHERE project_id=? ORDER BY created_at DESC", (pid,))]


def get_skill(project, name_or_id) -> dict | None:
    pid = service._pid(project)
    return load_row(db.one(
        "SELECT * FROM skills WHERE project_id=? AND (name=? OR id=?)",
        (pid, name_or_id, name_or_id)), ("steps",))
