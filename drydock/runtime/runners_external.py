"""External runners — Claude Code / Codex as the execution engine for a run.

The agent runs *inside* a provisioned Drydock workspace (tier 0/1/2). Governance
comes from the hook layer (drydock hooks install), so accountability never depends
on parsing the agent's output; the transcript capture below is best-effort.

Phase 2 ships the `claude` runner (headless `claude -p`). `codex` mirrors it via
`codex exec`. Both require the respective CLI on PATH; when absent we return a
clear error rather than pretending.
"""
from __future__ import annotations

import shutil
import subprocess

from ..sandbox.tier0 import Tier0Provider
from ..store import planning, runs as runs_store, service
from ..store import tickets as tickets_mod


def run_claude(project, ticket=None, tier=0, instruction=None,
               model=None, timeout=1800) -> dict:
    if not shutil.which("claude"):
        return {"error": "claude CLI not found on PATH"}

    ticket_row = tickets_mod.get_ticket(project, ticket) if ticket else None
    ticket_key = (ticket_row or {}).get("key", "run")
    work_item_id = None
    if ticket_row:
        wi = service.list_work_items(project, ticket_id=ticket_row["id"])
        work_item_id = wi[0]["id"] if wi else None

    run = runs_store.create_run(project, ticket_id=(ticket_row or {}).get("id"),
                                work_item_id=work_item_id, runner="claude", tier=tier)
    prov = Tier0Provider(ticket_key=ticket_key)
    ws = prov.provision(project, run["id"])
    runs_store.set_run_workspace(run["id"], ws.id)

    # install capture hooks into the workspace so the external run is governed/visible
    try:
        from .hooks import install
        install(ws.root, service.get_project(project)["slug"])
    except Exception:
        pass

    prompt = instruction
    if not prompt and work_item_id:
        b = planning.task_brief(project, work_item_id)
        prompt = planning.render_brief(b)
    prompt = prompt or "Complete the task in this repository."

    runs_store.set_run_status(run["id"], "running")
    runs_store.add_event(run["id"], "status", {"status": "running", "runner": "claude"})
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"],
            cwd=ws.root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        runs_store.set_run_status(run["id"], "failed", summary="claude timed out")
        return {"run_id": run["id"], "status": "failed", "error": "timeout"}

    # best-effort transcript capture from stream-json lines
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line:
            runs_store.add_event(run["id"], "message", {"raw": line[:4000]})

    status = "done" if proc.returncode == 0 else "failed"
    runs_store.set_run_status(run["id"], status, summary=f"claude exit {proc.returncode}")
    return {"run_id": run["id"], "status": status, "workspace": ws.root,
            "exit_code": proc.returncode}
