"""Tickets — port of orbit ``tickets.py`` with per-project key sequences (TCK-1…)."""
from __future__ import annotations

from . import db, service
from .db import now, ulid


def create_ticket(project, title, body=None, priority=2, status="open") -> dict:
    pid = service._pid(project)
    with db.tx() as conn:
        row = conn.execute(
            "UPDATE projects SET ticket_seq = ticket_seq + 1 WHERE id=? "
            "RETURNING ticket_prefix, ticket_seq", (pid,)).fetchone()
        key = f"{row['ticket_prefix']}-{row['ticket_seq']}"
        tid = ulid()
        ts = now()
        conn.execute(
            """INSERT INTO tickets(id, project_id, key, title, body, status, priority,
                                   created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (tid, pid, key, title, body, status, int(priority), ts, ts))
    return db.one("SELECT * FROM tickets WHERE id=?", (tid,))


def get_ticket(project, ref) -> dict | None:
    """Look up by id or key (TCK-12)."""
    pid = service._pid(project)
    return db.one(
        "SELECT * FROM tickets WHERE project_id=? AND (id=? OR key=?)",
        (pid, ref, ref))


def list_tickets(project, status=None) -> list[dict]:
    pid = service._pid(project)
    sql, params = "SELECT * FROM tickets WHERE project_id=?", [pid]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY priority, updated_at DESC"
    return db.q(sql, params)


def update_ticket(project, ref, status=None, priority=None, title=None,
                  body=None, assignee_agent_id=None) -> dict | None:
    t = get_ticket(project, ref)
    if not t:
        return None
    sets, params = [], []
    for col, val in (("status", status), ("priority", priority), ("title", title),
                     ("body", body), ("assignee_agent_id", assignee_agent_id)):
        if val is not None:
            sets.append(f"{col}=?")
            params.append(val)
    if sets:
        sets.append("updated_at=?")
        params.extend([now(), t["id"]])
        db.execute(f"UPDATE tickets SET {', '.join(sets)} WHERE id=?", params)
    return db.one("SELECT * FROM tickets WHERE id=?", (t["id"],))


def assign_task(task_id, ticket_id) -> dict | None:
    db.execute(
        "UPDATE work_items SET ticket_id=?, updated_at=? WHERE id=?",
        (ticket_id, now(), task_id))
    return db.one("SELECT * FROM work_items WHERE id=?", (task_id,))
