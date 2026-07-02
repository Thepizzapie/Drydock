"""Runners — a run's pluggable execution engine (DESIGN.md D13, §7b).

    native : Drydock's own session loop (this file wires it end to end)
    shell  : provision-only; print the sandbox path for a human/agent to work in
    claude : headless `claude -p <brief>` inside the workspace (Phase 2)
    codex  : `codex exec` inside the workspace (Phase 2)

start_run() is the single entry the CLI/server call. It provisions a workspace,
runs the engine, and returns a summary dict. Ask-pauses surface as
{"status": "waiting", "ask_id": ...}; resume_run() continues after resolution.
"""
from __future__ import annotations

from ..sandbox.tier0 import Tier0Provider
from ..store import registry, runs as runs_store, service
from ..store import tickets as tickets_mod
from . import agentdef as agentdef_mod
from .providers import get_provider
from .session import Session


def _provider_for(agentdef, tier, override=None):
    if override:
        return get_provider(override, agentdef.model)
    # default: anthropic if a model looks like claude, else mock is never auto-picked
    model = agentdef.model or "claude-sonnet-5"
    name = "anthropic" if str(model).startswith("claude") else "openai"
    return get_provider(name, model)


def _load_agentdef(project, agent_ref):
    """Resolve an agent by name from the registry, or from a .md path."""
    import os
    if os.path.exists(agent_ref) and agent_ref.endswith(".md"):
        ad = agentdef_mod.load_file(agent_ref)
        agentdef_mod.register(project, ad, definition_md=open(agent_ref, encoding="utf-8").read())
        return ad
    row = registry.get_agent(project, agent_ref)
    if not row:
        raise ValueError(f"unknown agent: {agent_ref}")
    # reconstruct an AgentDef from the stored definition
    fm = row.get("definition") or {}
    fm.setdefault("name", row["name"])
    fm.setdefault("model", row.get("model"))
    fm.setdefault("tools", row.get("tools") or agentdef_mod.DEFAULT_TOOLS)
    md = row.get("definition_md")
    if md:
        return agentdef_mod.parse(md)
    ad = agentdef_mod.AgentDef(
        name=row["name"], description=row.get("description") or "",
        model=row.get("model"), tools=row.get("tools") or agentdef_mod.DEFAULT_TOOLS,
        permissions=fm.get("permissions") or {}, raw_frontmatter=fm,
        system_prompt=row.get("description") or "")
    return ad


def start_run(project, agent_ref, ticket=None, tier=0, provider_override=None,
              instruction=None, runner="native", ask_resolver=None) -> dict:
    ad = _load_agentdef(project, agent_ref)

    ticket_row = tickets_mod.get_ticket(project, ticket) if ticket else None
    work_item_id = None
    ticket_key = "run"
    if ticket_row:
        ticket_key = ticket_row["key"]
        wi = service.list_work_items(project, ticket_id=ticket_row["id"])
        work_item_id = wi[0]["id"] if wi else None

    agent_row = registry.get_agent(project, ad.name)
    run = runs_store.create_run(
        project, agent_id=(agent_row or {}).get("id"),
        ticket_id=(ticket_row or {}).get("id"), work_item_id=work_item_id,
        runner=runner, tier=tier, model=ad.model)

    if runner == "shell":
        prov = Tier0Provider(ticket_key=ticket_key)
        ws = prov.provision(project, run["id"])
        runs_store.set_run_workspace(run["id"], ws.id)
        runs_store.set_run_status(run["id"], "waiting", summary="shell: workspace ready")
        return {"status": "workspace_ready", "run_id": run["id"], "workspace": ws.root,
                "branch": ws.branch, "tier": tier}

    # native runner
    prov = Tier0Provider(ticket_key=ticket_key)  # tier 0 for Phase 1; 1/2 later
    ws = prov.provision(project, run["id"])
    runs_store.set_run_workspace(run["id"], ws.id)
    worker = prov.worker(ws)
    provider = _provider_for(ad, tier, override=provider_override)
    identity = f"{ad.name}@{run['id'][-6:]}"

    session = Session(project, run, ad, provider, ws, worker, identity=identity,
                      ask_resolver=ask_resolver)
    try:
        return session.run_loop(instruction=instruction)
    finally:
        worker.close()


def resume_run(run_id, ask_id, resolution) -> dict:
    """Resume a waiting run after an ask is resolved (Phase 2 drives this via the server).

    resolution: 'approved_once' | 'always' | 'denied'. On 'always' a grant is added.
    For Phase 1 this is exercised by tests; full mid-loop replay lands with the server.
    """
    ask = runs_store.get_ask(ask_id)
    if not ask or ask["status"] != "pending":
        return {"error": "ask not pending"}
    runs_store.resolve_ask(ask_id, resolution)
    # a full resume replays the pending tool call and continues the loop; the
    # server layer (Phase 2) reconstructs Session state from run_events. Here we
    # just record the resolution outcome.
    decision = "allow" if resolution in ("approved_once", "always") else "deny"
    runs_store.add_event(run_id, "status",
                         {"status": "resumed", "ask_id": ask_id, "resolution": resolution,
                          "effective": decision})
    return {"run_id": run_id, "ask_id": ask_id, "resolution": resolution,
            "effective_decision": decision}
