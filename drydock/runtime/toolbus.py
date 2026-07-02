"""The toolbus — the single execution path for every model tool call.

    tool_call
      -> kernel.check                    (aegis, host-side)
           allow -> worker.exec          (inside the sandbox)
           deny  -> error result (model sees the rule message, can adapt)
           ask   -> ask row + run 'waiting'; an AskResolver decides:
                      park    -> raise AskPending (headless/CLI: run exits, resumable)
                      block   -> wait for a human decision, then exec/deny in place
      -> audit row (always)
      -> run_event (always)
    -> ToolResult dict back to the session loop

The resolver is injected so the SAME loop works headless (park) or under the
server (block-until-resolved). "always" persists a policy grant and rebuilds the
kernel so future calls of the same shape are auto-allowed.
"""
from __future__ import annotations

import datetime

from ..sandbox.base import ToolResult
from ..store import runs as runs_store

DEFAULT_ASK_TTL_MIN = 60


class AskPending(Exception):
    def __init__(self, ask_id, tool, args, verdict):
        self.ask_id = ask_id
        self.tool = tool
        self.args = args
        self.verdict = verdict


def park_resolver(ask_id, run_id):
    """Headless resolver: don't wait — signal the caller to park the run."""
    raise _Park(ask_id)


class _Park(Exception):
    def __init__(self, ask_id):
        self.ask_id = ask_id


def _expiry(minutes=DEFAULT_ASK_TTL_MIN) -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=minutes)).isoformat()


class ToolBus:
    def __init__(self, run_id, kernel, worker, identity=None, ask_resolver=None,
                 project=None):
        self.run_id = run_id
        self.kernel = kernel
        self.worker = worker
        self.identity = identity
        self.project = project
        self.ask_resolver = ask_resolver or park_resolver

    def dispatch(self, tool: str, args: dict) -> dict:
        verdict = self.kernel.check(tool, args)
        decision = verdict.decision

        audit = runs_store.add_audit(
            decision=decision, event="PreToolUse", tool=tool,
            action=_action_for(tool), rule=verdict.rule, message=verdict.message,
            args=args, identity=self.identity, run_id=self.run_id)
        runs_store.add_event(self.run_id, "decision", {
            "tool": tool, "decision": decision,
            "rule": verdict.rule, "message": verdict.message})

        if decision == "deny":
            return self._deny_result(tool, verdict.message or "Denied by policy")

        if decision == "ask":
            ask = runs_store.create_ask(self.run_id, audit["id"], expires_at=_expiry())
            runs_store.set_run_status(self.run_id, "waiting")
            runs_store.add_event(self.run_id, "status",
                                 {"status": "waiting", "ask_id": ask["id"], "tool": tool})
            try:
                resolution = self.ask_resolver(ask["id"], self.run_id)
            except _Park as park:
                raise AskPending(park.ask_id, tool, args, verdict)
            return self._apply_resolution(resolution, ask["id"], tool, args, verdict)

        # allow
        return self._exec(tool, args)

    def _apply_resolution(self, resolution, ask_id, tool, args, verdict) -> dict:
        runs_store.set_run_status(self.run_id, "running")
        if resolution in ("approved_once", "always", "allow"):
            if resolution == "always":
                self._grant(tool, args, verdict)
            runs_store.add_event(self.run_id, "status",
                                 {"status": "resumed", "ask_id": ask_id,
                                  "resolution": resolution})
            return self._exec(tool, args)
        # denied / expired
        runs_store.add_event(self.run_id, "status",
                             {"status": "resumed", "ask_id": ask_id, "resolution": resolution})
        return self._deny_result(tool, f"approval {resolution}")

    def _grant(self, tool, args, verdict):
        if not self.project:
            return
        from .kernel import _TOOL_ACTION, _normalize_args
        scope = {"action_class": _TOOL_ACTION.get(tool, "other")}
        norm = _normalize_args(tool, args or {})
        if norm.get("file_path"):
            scope["file_path"] = norm["file_path"]
        try:
            runs_store.add_grant(self.project, rule=(verdict.rule or f"ask:{tool}"),
                                 scope=scope, created_by="human")
            self.kernel.rebuild()
        except Exception:
            pass

    def _exec(self, tool, args) -> dict:
        result = self.worker.exec(tool, args)
        runs_store.add_event(self.run_id, "tool_result", {"tool": tool, **result.to_dict()})
        return result.to_dict()

    def _deny_result(self, tool, msg) -> dict:
        result = ToolResult(False, error=f"[policy denied] {msg}")
        runs_store.add_event(self.run_id, "tool_result", {"tool": tool, **result.to_dict()})
        return result.to_dict()


def _action_for(tool: str) -> str:
    from .kernel import _TOOL_ACTION
    return _TOOL_ACTION.get(tool, "other")
