"""Planning core — port of orbit ``planning.py`` (pickup-ready tickets).

A ticket is not dispatched until it has a pinned plan, tasks broken out, and
each task scoped to its files. Owns:
  - create_ticket_from_plan: structured plan -> ticket + pinned memory + tasks + scopes
  - assign_files: file entities + scopes edges for a work_item
  - ticket_scope / ticket_readiness
  - task_brief + render_brief: the agent pickup packet
"""
from __future__ import annotations

import logging

from . import db, service
from .graph_links import _add_edge, _norm, ensure_file_entity

log = logging.getLogger(__name__)

# Structured plan shape:
# {"summary": str, "steps": [{"title", "files": [path], "suggested_role"}],
#  "risks": [str], "open_questions": [str]}


def _render_plan(plan: dict) -> str:
    lines = []
    if plan.get("summary"):
        lines.append(f"# Plan\n\n{plan['summary']}\n")
    steps = plan.get("steps") or []
    if steps:
        lines.append("## Steps\n")
        for i, step in enumerate(steps, 1):
            role = step.get("suggested_role") or ""
            role_note = f" [{role}]" if role else ""
            lines.append(f"{i}. **{step.get('title', '')}**{role_note}")
            for f in step.get("files") or []:
                lines.append(f"   - `{f}`")
    risks = plan.get("risks") or []
    if risks:
        lines.append("\n## Risks\n")
        for r in risks:
            lines.append(f"- {r}")
    oq = plan.get("open_questions") or []
    if oq:
        lines.append("\n## Open Questions\n")
        for q in oq:
            lines.append(f"- {q}")
    return "\n".join(lines)


def create_ticket_from_plan(project, plan: dict, priority: int = 2) -> dict:
    """plan -> ticket + pinned plan memory + tasks with file scopes. Idempotent-safe."""
    from . import tickets as tickets_mod

    pid = service._pid(project)
    p = service.get_project(project)
    root = p.get("root_path") if p else None

    summary = plan.get("summary") or "Untitled plan"
    ticket = tickets_mod.create_ticket(project, summary[:200], priority=priority)
    ticket_id = str(ticket["id"])

    plan_body = _render_plan(plan)
    mem = service.add_memory(
        project,
        body=plan_body,
        title=f"Plan: {ticket.get('key', ticket_id)} {summary[:60]}",
        kind="procedural",
        pinned=True,
        tags=["plan", ticket.get("key", "")],
        source_trust="user_asserted",
        importance=0.8,
        defer_embed=True,
    )
    plan_memory_id = str(mem["id"])
    _add_edge(pid, "memory", plan_memory_id, "ticket", ticket_id, "plan_for")

    tasks_out = []
    for step in plan.get("steps") or []:
        title = step.get("title") or "Untitled step"
        suggested_role = step.get("suggested_role") or ""
        body = f"suggested_role: {suggested_role}" if suggested_role else None
        try:
            task = service.create_work_item(
                project, title, type="task", status="open",
                priority=priority, body=body, ticket_id=ticket_id)
            task_id = str(task["id"])
        except Exception as exc:
            log.warning("create_ticket_from_plan: could not create task %r: %s", title, exc)
            continue

        scoped_paths = []
        for raw_path in step.get("files") or []:
            if not raw_path:
                continue
            path = _norm(raw_path, root)
            eid = ensure_file_entity(pid, path)
            if eid:
                _add_edge(pid, "work_item", task_id, "entity", eid, "scopes")
                scoped_paths.append(path)

        tasks_out.append({
            "task_id": task_id,
            "title": title,
            "files": scoped_paths,
            "suggested_role": suggested_role,
        })

    return {"ticket": ticket, "plan_memory_id": plan_memory_id, "tasks": tasks_out}


def assign_files(project, work_item_id, paths: list[str]) -> dict:
    pid = service._pid(project)
    p = service.get_project(project)
    root = p.get("root_path") if p else None

    assigned, already = [], 0
    for raw_path in (paths or []):
        if not raw_path:
            continue
        path = _norm(raw_path, root)
        eid = ensure_file_entity(pid, path)
        if not eid:
            continue
        if _add_edge(pid, "work_item", work_item_id, "entity", eid, "scopes"):
            assigned.append(path)
        else:
            already += 1
    return {"work_item_id": work_item_id, "assigned": assigned, "already_existed": already}


def _scoped_paths(pid: str, task_id: str) -> list[str]:
    rows = db.q(
        """SELECT e.name AS path
           FROM relationships r
           JOIN entities e ON e.id = r.dst_id
           WHERE r.project_id=? AND r.relation='scopes'
             AND r.src_type='work_item' AND r.dst_type='entity'
             AND r.valid_to IS NULL AND r.src_id=?""",
        (pid, task_id))
    return [r["path"] for r in rows]


def ticket_scope(project, ticket_id) -> dict:
    pid = service._pid(project)
    task_rows = db.q(
        "SELECT id FROM work_items WHERE ticket_id=? AND project_id=?", (ticket_id, pid))
    return {r["id"]: _scoped_paths(pid, r["id"]) for r in task_rows}


def ticket_readiness(project, ticket_id) -> dict:
    pid = service._pid(project)
    has_plan = db.one(
        """SELECT 1 AS x FROM relationships
           WHERE project_id=? AND relation='plan_for' AND dst_type='ticket'
             AND dst_id=? AND valid_to IS NULL LIMIT 1""",
        (pid, ticket_id)) is not None
    scope = ticket_scope(project, ticket_id)
    tasks_total = len(scope)
    tasks_scoped = sum(1 for paths in scope.values() if paths)
    ready = has_plan and tasks_total > 0 and tasks_scoped == tasks_total
    return {"ready": ready, "has_plan": has_plan,
            "tasks_total": tasks_total, "tasks_scoped": tasks_scoped}


def task_brief(project, task_id, include_seeds=True) -> dict:
    """Full pickup brief for an agent claiming a task (orbit contract preserved)."""
    from . import graph as graph_mod

    pid = service._pid(project)
    task_row = db.one(
        "SELECT id, title, status, ticket_id FROM work_items WHERE id=? AND project_id=?",
        (task_id, pid))
    if not task_row:
        return {"task": None, "ticket": None, "plan": None, "files": [],
                "siblings": [], "suggested_agents": 1, "needs_agents": False,
                "recall_seeds": [], "brand": ""}

    task = dict(task_row)
    ticket_id = task.get("ticket_id")

    ticket = None
    if ticket_id:
        ticket = db.one(
            "SELECT id, key, title, status FROM tickets WHERE id=? AND project_id=?",
            (ticket_id, pid))

    plan = None
    if ticket_id:
        plan = db.one(
            """SELECT m.id, m.title, m.body
               FROM memories m
               JOIN relationships r ON r.src_id = m.id
               WHERE r.project_id=? AND r.relation='plan_for'
                 AND r.src_type='memory' AND r.dst_type='ticket'
                 AND r.dst_id=? AND r.valid_to IS NULL
               ORDER BY m.created_at DESC LIMIT 1""",
            (pid, ticket_id))

    scoped_paths = _scoped_paths(pid, task_id)
    files = []
    for path in scoped_paths:
        try:
            ctx = graph_mod.file_context(project, path)
        except Exception:
            ctx = {"path": path, "found": False}
        files.append({"path": path, "context": ctx})

    siblings = []
    if ticket_id:
        siblings = db.q(
            """SELECT id, title, status FROM work_items
               WHERE ticket_id=? AND project_id=? AND id != ?
               ORDER BY priority, updated_at DESC""",
            (ticket_id, pid, task_id))

    has_ui = any("ui/" in p or p.startswith("ui/") for p in scoped_paths)
    has_py = any(p.endswith(".py") for p in scoped_paths)
    suggested_agents = 2 if (has_ui and has_py) or len(scoped_paths) > 6 else 1

    recall_seeds = []
    if include_seeds:
        try:
            seed_query = task["title"] + " " + " ".join(
                p.split("/")[-1] for p in scoped_paths[:4])
            for item in service.search_context(project, seed_query, k=5):
                recall_seeds.append({
                    "id": str(item.get("id") or ""),
                    "title": item.get("title") or "",
                    "kind": item.get("kind") or "",
                    "type": "memory",
                })
        except Exception as exc:
            log.debug("task_brief: recall_seeds failed: %s", exc)

    return {
        "task": task,
        "ticket": ticket,
        "plan": plan,
        "files": files,
        "siblings": siblings,
        "suggested_agents": suggested_agents,
        "needs_agents": suggested_agents > 1,
        "recall_seeds": recall_seeds,
        "brand": "",
    }


def render_brief(brief: dict) -> str:
    """Paste-ready text block for an agent (orbit render, minus orbit-specific preamble)."""
    lines = []
    lines.append("# BEFORE EDITING")
    lines.append("")
    lines.append("1. Read the scoped files + their context below")
    lines.append("2. Search project memory if you need more context")
    lines.append("3. Log a decision for any real choice")
    lines.append("")

    ticket = brief.get("ticket")
    task = brief.get("task")
    if ticket or task:
        lines.append("# TICKET & TASK")
        lines.append("")
        if ticket:
            key = ticket.get("key", "")
            t = f"{key}: {ticket.get('title', '')}" if key else ticket.get("title", "")
            lines.append(f"**Ticket:** {t}")
        if task:
            lines.append(f"**Task:** {task.get('title', '')}")
        lines.append("")

    plan = brief.get("plan")
    if plan and plan.get("body"):
        lines.append("# PLAN")
        lines.append("")
        lines.append(plan["body"])
        lines.append("")

    files = brief.get("files") or []
    if files:
        lines.append("# SCOPED FILES")
        lines.append("")
        for fi in files:
            path = fi.get("path", "")
            ctx = fi.get("context") or {}
            if not path:
                continue
            lines.append(f"## {path}")
            lines.append("")
            if ctx.get("found"):
                if ctx.get("connected_files"):
                    lines.append("**Connected files:**")
                    for cf in ctx["connected_files"][:3]:
                        lines.append(f"  - {cf}")
                    lines.append("")
                if ctx.get("recent_commits"):
                    lines.append("**Recent commits:**")
                    for rc in ctx["recent_commits"][:2]:
                        lines.append(f"  - {rc}")
                    lines.append("")
                if ctx.get("content"):
                    lines.append("**Content:**")
                    content = ctx["content"]
                    lines.append(content[:500] + "..." if len(content) > 500 else content)
                    lines.append("")
            else:
                lines.append("(file not found in graph)")
                lines.append("")

    seeds = brief.get("recall_seeds") or []
    if seeds:
        lines.append("# RECALL SEEDS")
        lines.append("")
        for seed in seeds:
            if seed.get("title"):
                kind = f" [{seed['kind']}]" if seed.get("kind") else ""
                lines.append(f"- {seed['title']}{kind}")
        lines.append("")

    siblings = brief.get("siblings") or []
    if siblings:
        lines.append("# SIBLING TASKS")
        lines.append("")
        for sib in siblings:
            if sib.get("title"):
                status = f" ({sib['status']})" if sib.get("status") else ""
                lines.append(f"- {sib['title']}{status}")
        lines.append("")

    return "\n".join(lines)
