"""FastAPI app — REST + SSE over the Drydock store. Localhost bind, no auth by default.

Mounts the static UI at / when built (ui/out). Everything the dashboard needs:
projects, tickets, memory, runs (+ live event stream), asks (+ resolve), audit, stats.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..store import allocator, fts, planning, registry, runs as runs_store, service
from ..store import tickets as tickets_mod
from .runmanager import MANAGER

app = FastAPI(title="Drydock", version="0.1.0")


@app.exception_handler(ValueError)
async def _value_error(_req: Request, exc: ValueError):
    return JSONResponse(status_code=404, content={"error": str(exc)})


# ── projects ──
@app.get("/api/projects")
def api_projects():
    return service.list_projects()


@app.get("/api/projects/{project}")
def api_project(project: str):
    p = service.get_project(project)
    if not p:
        raise HTTPException(404, "project not found")
    return p


@app.get("/api/projects/{project}/overview")
def api_overview(project: str):
    """Everything the Mission Control page needs in one call."""
    tickets = tickets_mod.list_tickets(project)
    open_tickets = [t for t in tickets if t["status"] not in ("done", "archived")]
    ready = [t for t in tickets if t["status"] == "ready"]
    runs = runs_store.list_runs(project, limit=20)
    running = [r for r in runs if r["status"] == "running"]
    asks = _asks_with_detail(runs_store.list_asks(status="pending", project=project))
    audit = runs_store.list_audit(project=project, limit=25)
    decided = runs_store.list_audit(project=project, limit=500)
    outcomes = {"allow": 0, "deny": 0, "ask": 0}
    for a in decided:
        outcomes[a["decision"]] = outcomes.get(a["decision"], 0) + 1
    return {
        "project": service.get_project(project),
        "counts": {"open_tickets": len(open_tickets), "ready": len(ready),
                   "running": len(running), "pending_asks": len(asks),
                   "audit_today": len(decided)},
        "sessions": runs,
        "asks": asks,
        "decision_feed": audit,
        "outcomes": outcomes,
        "handoff": service.get_handoff(project),
    }


# ── tickets / work ──
@app.get("/api/projects/{project}/tickets")
def api_tickets(project: str, status: str | None = None):
    return tickets_mod.list_tickets(project, status=status)


@app.get("/api/projects/{project}/tickets/{ref}")
def api_ticket(project: str, ref: str):
    t = tickets_mod.get_ticket(project, ref)
    if not t:
        raise HTTPException(404, "ticket not found")
    wi = service.list_work_items(project, ticket_id=t["id"])
    return {"ticket": t, "work_items": wi}


@app.get("/api/tasks/{task_id}/brief")
def api_brief(project: str, task_id: str):
    b = planning.task_brief(project, task_id)
    b["rendered"] = planning.render_brief(b)
    return b


# ── memory ──
@app.get("/api/projects/{project}/memory/search")
def api_memory_search(project: str, q: str = "", k: int = 8):
    return service.search_context(project, q, k=k)


@app.get("/api/projects/{project}/context")
def api_context(project: str, q: str | None = None, budget: int = 2000):
    return allocator.assemble(project, token_budget=budget, query=q)


@app.get("/api/projects/{project}/decisions")
def api_decisions(project: str, active_only: bool = True):
    return service.get_decisions(project, active_only=active_only)


# ── runs ──
@app.get("/api/projects/{project}/runs")
def api_runs(project: str, status: str | None = None):
    return runs_store.list_runs(project, status=status)


@app.get("/api/runs/{run_id}")
def api_run(run_id: str):
    r = runs_store.get_run(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return {"run": r, "events": runs_store.get_events(run_id),
            "workspace": runs_store.get_workspace(r["workspace_id"]) if r.get("workspace_id") else None}


@app.get("/api/runs/{run_id}/diff")
def api_run_diff(run_id: str):
    r = runs_store.get_run(run_id)
    if not r or not r.get("workspace_id"):
        raise HTTPException(404, "no workspace")
    from ..sandbox import worktree
    ws = runs_store.get_workspace(r["workspace_id"])
    if ws["kind"] != "worktree":
        return {"diff": ""}
    return {"diff": worktree.diff(ws["path"], ws["base_commit"])}


@app.get("/api/runs/{run_id}/events")
async def api_run_events(run_id: str, after: int = 0):
    """Server-Sent Events: stream run_events as they land, then keep-alive."""
    async def gen():
        seq = after
        idle = 0
        while True:
            events = runs_store.get_events(run_id, after_seq=seq)
            for e in events:
                seq = e["seq"]
                yield f"data: {json.dumps(e)}\n\n"
            run = runs_store.get_run(run_id)
            if run and run["status"] in ("done", "failed", "killed") and not events:
                yield f"event: end\ndata: {json.dumps({'status': run['status']})}\n\n"
                return
            idle = idle + 1 if not events else 0
            if idle > 600:  # ~5 min of nothing -> stop
                return
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/projects/{project}/dispatch")
async def api_dispatch(project: str, body: dict):
    agent = body.get("agent")
    if not agent:
        raise HTTPException(400, "agent required")
    return MANAGER.dispatch(
        project, agent, ticket=body.get("ticket"), tier=body.get("tier", 0),
        provider_override=body.get("provider"), instruction=body.get("instruction"))


# ── agents ──
@app.get("/api/projects/{project}/agents")
def api_agents(project: str):
    return registry.list_agents(project)


@app.get("/api/projects/{project}/agents/{name}")
def api_agent(project: str, name: str):
    a = registry.get_agent(project, name)
    if not a:
        raise HTTPException(404, "agent not found")
    return a


# ── approvals ──
def _asks_with_detail(asks: list) -> list:
    out = []
    for a in asks:
        aud = runs_store.list_audit(run_id=a["run_id"], limit=50)
        match = next((x for x in aud if x["id"] == a["audit_id"]), None)
        out.append({**a, "detail": match})
    return out


@app.get("/api/asks")
def api_asks(project: str | None = None):
    return _asks_with_detail(runs_store.list_asks(status="pending", project=project))


@app.post("/api/asks/{ask_id}/resolve")
def api_resolve(ask_id: str, body: dict):
    resolution = body.get("resolution")
    if resolution not in ("approved_once", "always", "denied"):
        raise HTTPException(400, "resolution must be approved_once|always|denied")
    signalled = MANAGER.resolve(ask_id, resolution, by=body.get("by", "human"))
    return {"ask_id": ask_id, "resolution": resolution, "signalled_live_run": signalled}


# ── audit / stats ──
@app.get("/api/projects/{project}/audit")
def api_audit(project: str, decision: str | None = None, limit: int = 200):
    return runs_store.list_audit(project=project, decision=decision, limit=limit)


@app.get("/api/projects/{project}/stats/tokens")
def api_tokens(project: str):
    runs = runs_store.list_runs(project, limit=500)
    by_ticket: dict = {}
    total = 0
    for r in runs:
        tot = (r["tokens_in"] or 0) + (r["tokens_out"] or 0)
        total += tot
        key = r.get("ticket_id") or "unassigned"
        by_ticket[key] = by_ticket.get(key, 0) + tot
    return {"total": total, "by_ticket": by_ticket}


# ── system ──
@app.get("/api/system/tiers")
def api_tiers():
    from ..sandbox import detect
    return detect.tiers()


@app.get("/api/system/doctor")
def api_doctor():
    from .. import config
    from ..sandbox import detect
    from ..store import embeddings
    vectors = True
    try:
        import chromadb  # noqa: F401
    except ImportError:
        vectors = False
    return {
        "home": str(config.home()),
        "db": str(config.db_path()),
        "git": detect.git_available(),
        "wsl": detect.wsl_available(),
        "docker": detect.docker_available(),
        "embeddings": embeddings.backend(),
        "vectors": vectors,
        "recommended_tier": detect.recommended_tier(),
    }


@app.get("/api/health")
def api_health():
    return {"ok": True, "version": "0.1.0"}


def _mount_ui():
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles
    ui_dir = Path(__file__).parent.parent / "_data" / "ui"
    if ui_dir.exists():
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")


_mount_ui()


def serve(host="127.0.0.1", port=4400):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")
