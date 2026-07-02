"""Run manager — runs sessions in background threads with a blocking ask resolver.

The dashboard dispatches a run; it executes on a daemon thread. When a tool call
hits an `ask`, the thread blocks on a per-ask Event until the approvals endpoint
resolves it (or the ask expires). This keeps the whole session loop alive and
resumable in place — no state reconstruction.

SQLite is WAL, so the main (request) thread reads while run threads write.
"""
from __future__ import annotations

import threading

from ..store import runs as runs_store

# how long a run thread waits for a human before auto-denying (seconds)
_ASK_WAIT_SECONDS = 60 * 60


class RunManager:
    def __init__(self):
        self._pending: dict[str, dict] = {}   # ask_id -> {event, resolution}
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    # ── ask resolver (injected into the toolbus) ──
    def _resolver(self, ask_id, run_id) -> str:
        ev = threading.Event()
        with self._lock:
            self._pending[ask_id] = {"event": ev, "resolution": None}
        resolved = ev.wait(timeout=_ASK_WAIT_SECONDS)
        with self._lock:
            info = self._pending.pop(ask_id, None)
        if not resolved or not info or not info["resolution"]:
            runs_store.resolve_ask(ask_id, "expired")
            return "denied"
        return info["resolution"]

    def resolve(self, ask_id, resolution, by=None) -> bool:
        """Resolve a pending ask. Returns True if a waiting run was signalled."""
        runs_store.resolve_ask(ask_id, resolution, resolved_by=by)
        with self._lock:
            info = self._pending.get(ask_id)
        if info:
            info["resolution"] = resolution
            info["event"].set()
            return True
        return False  # parked run (not live in this process) — resolution recorded only

    # ── dispatch ──
    def dispatch(self, project, agent, ticket=None, tier=0, provider_override=None,
                 instruction=None) -> dict:
        from ..runtime import runner

        # create the run synchronously so we can return its id immediately
        result_box: dict = {}
        ready = threading.Event()

        def _work():
            try:
                out = runner.start_run(
                    project, agent, ticket=ticket, tier=tier,
                    provider_override=provider_override, instruction=instruction,
                    ask_resolver=self._resolver)
                result_box["result"] = out
            except Exception as exc:  # noqa: BLE001
                result_box["error"] = str(exc)
            finally:
                ready.set()

        t = threading.Thread(target=_work, daemon=True)
        t.start()
        # give the thread a moment to create the run row and register it
        ready.wait(timeout=1.5)
        # find the newest run for this project (the one we just started)
        runs = runs_store.list_runs(project, limit=1)
        run_id = runs[0]["id"] if runs else None
        if run_id:
            self._threads[run_id] = t
        if result_box:
            return {"run_id": run_id, "status": "finished", **result_box}
        return {"run_id": run_id, "status": "running"}


MANAGER = RunManager()
