"""The toolbus — the single execution path for every model tool call.

    tool_call
      -> kernel.check                    (aegis, host-side)
           allow -> worker.exec          (inside the sandbox)
           deny  -> error result (model sees the rule message, can adapt)
           ask   -> ask row + run 'waiting'; resolved out-of-band, then exec/deny
      -> audit row (always)
      -> run_event (always)
    -> ToolResult dict back to the session loop

The `ask` path is cooperative: dispatch() raises AskPending, the session loop
persists state and returns; the run resumes when the ask is resolved.
"""
from __future__ import annotations

import datetime

from ..sandbox.base import ToolResult
from ..store import runs as runs_store


class AskPending(Exception):
    def __init__(self, ask_id, tool, args, verdict):
        self.ask_id = ask_id
        self.tool = tool
        self.args = args
        self.verdict = verdict


DEFAULT_ASK_TTL_MIN = 60


def _expiry(minutes=DEFAULT_ASK_TTL_MIN) -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=minutes)).isoformat()


class ToolBus:
    def __init__(self, run_id, kernel, worker, identity=None):
        self.run_id = run_id
        self.kernel = kernel
        self.worker = worker
        self.identity = identity

    def dispatch(self, tool: str, args: dict, *, preresolved: str | None = None) -> dict:
        """Run one tool call through policy + sandbox. Returns a ToolResult dict.

        preresolved: when resuming after an ask, 'allow' or 'deny' skips re-check.
        """
        verdict = None
        if preresolved is None:
            verdict = self.kernel.check(tool, args)
            decision = verdict.decision
        else:
            decision = preresolved

        # audit every decision
        audit = runs_store.add_audit(
            decision=decision,
            event="PreToolUse", tool=tool,
            action=_action_for(tool),
            rule=(verdict.rule if verdict else None),
            message=(verdict.message if verdict else None),
            args=args, identity=self.identity, run_id=self.run_id)
        runs_store.add_event(self.run_id, "decision", {
            "tool": tool, "decision": decision,
            "rule": verdict.rule if verdict else None,
            "message": verdict.message if verdict else None})

        if decision == "deny":
            msg = (verdict.message if verdict else None) or "Denied by policy"
            result = ToolResult(False, error=f"[policy denied] {msg}")
            runs_store.add_event(self.run_id, "tool_result",
                                 {"tool": tool, **result.to_dict()})
            return result.to_dict()

        if decision == "ask":
            ask = runs_store.create_ask(self.run_id, audit["id"], expires_at=_expiry())
            runs_store.set_run_status(self.run_id, "waiting")
            runs_store.add_event(self.run_id, "status",
                                 {"status": "waiting", "ask_id": ask["id"], "tool": tool})
            raise AskPending(ask["id"], tool, args, verdict)

        # allow -> execute in the sandbox
        result = self.worker.exec(tool, args)
        runs_store.add_event(self.run_id, "tool_result", {"tool": tool, **result.to_dict()})
        return result.to_dict()


def _action_for(tool: str) -> str:
    from .kernel import _TOOL_ACTION
    return _TOOL_ACTION.get(tool, "other")
