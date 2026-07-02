"""Drydock MCP server (stdio, FastMCP).

Preserves orbit's tool surface for the PM plane so existing workflows carry
over. Runtime tools (dispatch_agent, resolve_ask, …) land in Phase 2.

Register with Claude Code:
    claude mcp add drydock -- drydock mcp
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..store import allocator, fts, planning, registry, service
from ..store import tickets as tickets_mod

mcp = FastMCP("drydock")


# ── projects & repos ────────────────────────────────────────────────────────

@mcp.tool()
def create_project(name: str, root_path: str | None = None, description: str | None = None,
                   slug: str | None = None, ticket_prefix: str | None = None):
    """Create a Drydock project (the container for tickets, memory, agents, runs)."""
    return service.create_project(name, root_path=root_path, description=description,
                                  slug=slug, ticket_prefix=ticket_prefix)


@mcp.tool()
def list_projects():
    """List all projects."""
    return service.list_projects()


@mcp.tool()
def get_project(project: str):
    """Get one project by slug, id, or name."""
    return service.get_project(project)


@mcp.tool()
def add_repo(project: str, root_path: str, name: str | None = None,
             is_primary: bool = False):
    """Attach a repo to a project."""
    return service.add_repo(project, root_path, name=name, is_primary=is_primary)


@mcp.tool()
def list_repos(project: str):
    """List repos attached to a project."""
    return service.list_repos(project)


# ── recall / memory ─────────────────────────────────────────────────────────

@mcp.tool()
def resume(project: str, token_budget: int = 2000):
    """Session-start packet: handoff + active decisions + open work + budget-packed context."""
    return service.resume(project, token_budget=token_budget)


@mcp.tool()
def search_context(project: str, query: str, k: int = 5, kind: str | None = None):
    """Hybrid recall over project memories (FTS5 + vectors when available)."""
    return service.search_context(project, query, k=k, kind=kind)


@mcp.tool()
def assemble_context(project: str, query: str | None = None, token_budget: int = 2000):
    """Budget-aware context packet (greedy knapsack over pinned/handoff/decisions/work/memories)."""
    packet = allocator.assemble(project, token_budget=token_budget, query=query)
    packet["rendered"] = allocator.render(packet)
    return packet


@mcp.tool()
def add_memory(project: str, body: str, title: str | None = None, kind: str = "episodic",
               tags: list[str] | None = None, importance: float = 0.5,
               pinned: bool = False):
    """Store a memory. kind: episodic|semantic|procedural|reference."""
    return service.add_memory(project, body, title=title, kind=kind, tags=tags,
                              importance=importance, pinned=pinned)


@mcp.tool()
def pin(memory_id: str, pinned: bool = True):
    """Pin/unpin a memory (pinned memories always ship in assembled context)."""
    return service.pin(memory_id, pinned=pinned)


# ── decisions / attempts / handoffs ─────────────────────────────────────────

@mcp.tool()
def log_decision(project: str, title: str, rationale: str | None = None,
                 alternatives: list[str] | None = None,
                 supersedes: str | None = None, ticket_id: str | None = None):
    """Log a project decision (architectural/product choice — not policy allow/deny)."""
    return service.log_decision(project, title, rationale=rationale,
                                alternatives=alternatives, supersedes=supersedes,
                                ticket_id=ticket_id)


@mcp.tool()
def get_decisions(project: str, active_only: bool = True):
    """List project decisions."""
    return service.get_decisions(project, active_only=active_only)


@mcp.tool()
def log_attempt(project: str, what_tried: str, outcome: str, why: str | None = None,
                work_item_id: str | None = None):
    """Record an attempt + outcome (what was tried, did it work, why)."""
    return service.log_attempt(project, what_tried, outcome, why=why,
                               work_item_id=work_item_id)


@mcp.tool()
def get_attempts(project: str, work_item_id: str | None = None):
    """List recorded attempts."""
    return service.get_attempts(project, work_item_id=work_item_id)


@mcp.tool()
def create_handoff(project: str, summary: str | None = None,
                   current_state: str | None = None,
                   next_steps: list[str] | None = None,
                   blockers: list[str] | None = None):
    """Write the session handoff (consumes the previous active one)."""
    return service.create_handoff(project, summary=summary, current_state=current_state,
                                  next_steps=next_steps, blockers=blockers)


@mcp.tool()
def get_handoff(project: str):
    """Get the active handoff."""
    return service.get_handoff(project)


# ── work: tickets & tasks ───────────────────────────────────────────────────

@mcp.tool()
def create_ticket(project: str, title: str, body: str | None = None,
                  priority: int = 2):
    """Create a ticket (gets a project-prefixed key like TCK-12)."""
    return tickets_mod.create_ticket(project, title, body=body, priority=priority)


@mcp.tool()
def list_tickets(project: str, status: str | None = None):
    """List tickets, optionally by status (open|ready|in_progress|review|done|archived)."""
    return tickets_mod.list_tickets(project, status=status)


@mcp.tool()
def get_ticket(project: str, ref: str):
    """Get a ticket by id or key."""
    return tickets_mod.get_ticket(project, ref)


@mcp.tool()
def update_ticket(project: str, ref: str, status: str | None = None,
                  priority: int | None = None, title: str | None = None,
                  body: str | None = None):
    """Update ticket fields."""
    return tickets_mod.update_ticket(project, ref, status=status, priority=priority,
                                     title=title, body=body)


@mcp.tool()
def search_tickets(project: str, query: str, k: int = 10):
    """Full-text search over tickets."""
    return fts.search_tickets(project, query, k=k)


@mcp.tool()
def create_work_item(project: str, title: str, body: str | None = None,
                     status: str = "open", priority: int = 2,
                     ticket_id: str | None = None):
    """Create a task/work item, optionally under a ticket."""
    return service.create_work_item(project, title, body=body, status=status,
                                    priority=priority, ticket_id=ticket_id)


@mcp.tool()
def update_work_item(id: str, status: str | None = None, priority: int | None = None,
                     title: str | None = None, body: str | None = None):
    """Update a work item."""
    return service.update_work_item(id, status=status, priority=priority,
                                    title=title, body=body)


@mcp.tool()
def list_work_items(project: str, status: str | None = None,
                    ticket_id: str | None = None):
    """List work items, optionally by status or ticket."""
    return service.list_work_items(project, status=status, ticket_id=ticket_id)


@mcp.tool()
def assign_task(task_id: str, ticket_id: str):
    """Attach a work item to a ticket."""
    return tickets_mod.assign_task(task_id, ticket_id)


# ── planning (pickup-ready tickets) ─────────────────────────────────────────

@mcp.tool()
def create_ticket_from_plan(project: str, plan: dict, priority: int = 2):
    """Structured plan -> ticket + pinned plan memory + tasks scoped to files.

    plan: {summary, steps:[{title, files:[path], suggested_role}], risks:[], open_questions:[]}
    """
    return planning.create_ticket_from_plan(project, plan, priority=priority)


@mcp.tool()
def assign_files(project: str, work_item_id: str, paths: list[str]):
    """Scope a work item to files (creates file entities + scopes edges)."""
    return planning.assign_files(project, work_item_id, paths)


@mcp.tool()
def ticket_readiness(project: str, ticket_id: str):
    """Is this ticket dispatch-ready? (has plan + every task scoped)"""
    return planning.ticket_readiness(project, ticket_id)


@mcp.tool()
def task_brief(project: str, task_id: str, rendered: bool = False):
    """Full pickup brief for a task: plan slice, scoped files with context, siblings, recall seeds."""
    brief = planning.task_brief(project, task_id)
    if rendered:
        brief["rendered"] = planning.render_brief(brief)
    return brief


# ── registry ────────────────────────────────────────────────────────────────

@mcp.tool()
def register_agent(project: str, name: str, description: str | None = None,
                   definition: dict | None = None, model: str | None = None,
                   tools: list[str] | None = None):
    """Register/update an agent definition (upsert by name, version bumps)."""
    return registry.register_agent(project, name, description=description,
                                   definition=definition, model=model, tools=tools)


@mcp.tool()
def list_agents(project: str):
    """List registered agents (project + global)."""
    return registry.list_agents(project)


@mcp.tool()
def get_agent(project: str, name_or_id: str):
    """Get one agent."""
    return registry.get_agent(project, name_or_id)


@mcp.tool()
def register_skill(project: str, name: str, description: str | None = None,
                   body: str | None = None, steps: list | None = None,
                   level: str = "skill"):
    """Register/update a skill (macro|skill|sub_agent)."""
    return registry.register_skill(project, name, description=description, body=body,
                                   steps=steps, level=level)


@mcp.tool()
def list_skills(project: str):
    """List skills."""
    return registry.list_skills(project)


# ── graph ───────────────────────────────────────────────────────────────────

@mcp.tool()
def relate(project: str, src_type: str, src_id: str, dst_type: str, dst_id: str,
           relation: str):
    """Add a typed edge (mentions|co_changed|part_of|scopes|plan_for)."""
    return service.relate(project, src_type, src_id, dst_type, dst_id, relation)


@mcp.tool()
def get_related(project: str, entity_name: str):
    """Neighbors of a named entity in the project graph."""
    return service.get_related(project, entity_name)


@mcp.tool()
def file_context(project: str, path: str):
    """Pre-aimed context for one file: graph links, recent commits, content head."""
    from ..store import graph
    return graph.file_context(project, path)


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
