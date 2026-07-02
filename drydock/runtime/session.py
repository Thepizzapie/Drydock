"""The native agent loop.

    build system prompt (agent def + rendered task_brief, budget-packed)
    loop:
      provider.complete(system, messages, tools)
      record assistant turn (text + tool_calls) as run_events
      for each tool_call:
        toolbus.dispatch  ── kernel.check → sandbox exec → audit/event
        task_done → finish
        AskPending → persist state, set run 'waiting', return (resumable)
      append tool_results, repeat
    exit on: task_done | max_turns | budget ceiling | error

Messages use the internal shape providers translate (Anthropic-native blocks).
"""
from __future__ import annotations

from ..store import planning, registry, runs as runs_store, service
from . import toolbus as toolbus_mod
from .budget import Budget
from .kernel import Kernel
from .providers.base import Turn
from .tools import schemas_for


class Session:
    def __init__(self, project, run, agentdef, provider, workspace, worker,
                 identity=None, ask_resolver=None):
        self.project = project
        self.run = run
        self.run_id = run["id"]
        self.agentdef = agentdef
        self.provider = provider
        self.workspace = workspace
        self.kernel = Kernel(project, agentdef, workspace_root=workspace.root,
                             identity=identity)
        self.bus = toolbus_mod.ToolBus(self.run_id, self.kernel, worker,
                                       identity=identity, ask_resolver=ask_resolver,
                                       project=project)
        self.budget = Budget(agentdef.budget)
        self.tools = schemas_for(agentdef.tools)
        self.messages: list = []

    # ── prompt assembly ──
    def _system(self) -> str:
        parts = [self.agentdef.system_prompt or f"You are {self.agentdef.name}."]
        brief = None
        wid = self.run.get("work_item_id")
        if wid:
            try:
                b = planning.task_brief(self.project, wid)
                brief = planning.render_brief(b)
            except Exception:
                brief = None
        if brief:
            parts.append("\n---\n" + brief)
        parts.append(
            "\nYou are working in an isolated sandbox workspace. Use the tools to "
            "inspect and change files. Call task_done with a summary when finished. "
            "Some actions may be denied or held for human approval by policy — if a "
            "tool is denied, adapt rather than retrying the same call.")
        return "\n".join(parts)

    def _seed_user_message(self, instruction: str | None):
        text = instruction or "Complete the task described in your brief."
        self.messages.append({"role": "user", "content": text})

    # ── loop ──
    def run_loop(self, instruction: str | None = None) -> dict:
        runs_store.set_run_status(self.run_id, "running")
        runs_store.add_event(self.run_id, "status", {"status": "running"})
        if not self.messages:
            self._seed_user_message(instruction)

        system = self._system()
        for _turn in range(self.agentdef.max_turns):
            if self.budget.exceeded():
                return self._finish("failed", "budget ceiling reached")

            turn: Turn = self.provider.complete(system, self.messages, self.tools)
            self._account(turn)

            # record assistant turn
            assistant_content = []
            if turn.text:
                assistant_content.append({"type": "text", "text": turn.text})
                runs_store.add_event(self.run_id, "message",
                                     {"role": "assistant", "text": turn.text})
            for tc in turn.tool_calls:
                assistant_content.append({"type": "tool_use", "id": tc.id,
                                          "name": tc.name, "input": tc.args})
                runs_store.add_event(self.run_id, "tool_call",
                                     {"id": tc.id, "name": tc.name, "input": tc.args})
            self.messages.append({"role": "assistant", "content": assistant_content})

            if not turn.tool_calls:
                return self._finish("done", turn.text or "(no tool calls)")

            # execute tool calls, build tool_result blocks
            results = []
            for tc in turn.tool_calls:
                if tc.name == "task_done":
                    summary = (tc.args or {}).get("summary", "done")
                    return self._finish("done", summary)
                try:
                    res = self.bus.dispatch(tc.name, tc.args)
                except toolbus_mod.AskPending as ask:
                    # persist the pending tool call on the message so resume can replay it
                    runs_store.add_event(self.run_id, "status",
                                         {"status": "waiting", "ask_id": ask.ask_id,
                                          "pending_tool": {"id": tc.id, "name": tc.name,
                                                           "args": tc.args}})
                    return {"status": "waiting", "ask_id": ask.ask_id, "run_id": self.run_id}
                results.append({"type": "tool_result", "tool_use_id": tc.id,
                                "content": _result_block(res)})
            self.messages.append({"role": "user", "content": results})

        return self._finish("failed", f"max_turns ({self.agentdef.max_turns}) reached")

    # ── bookkeeping ──
    def _account(self, turn: Turn):
        self.budget.add(turn.tokens_in, turn.tokens_out)
        cost = 0
        if hasattr(self.provider, "cost_cents"):
            cost = self.provider.cost_cents(turn.tokens_in, turn.tokens_out)
        runs_store.add_run_tokens(self.run_id, turn.tokens_in, turn.tokens_out, cost)

    def _finish(self, status, summary) -> dict:
        runs_store.set_run_status(self.run_id, status, summary=summary)
        runs_store.add_event(self.run_id, "status", {"status": status, "summary": summary})
        # auto-handoff if the run didn't cleanly complete
        if status != "done":
            try:
                service.create_handoff(
                    self.project,
                    summary=f"Run {self.run_id[-6:]} ended: {status}",
                    current_state=summary, run_id=self.run_id)
            except Exception:
                pass
        return {"status": status, "summary": summary, "run_id": self.run_id,
                "tokens": self.budget.totals()}


def _result_block(res: dict):
    text = res.get("output") or ""
    if not res.get("ok"):
        text = (res.get("error") or "error") + (("\n" + text) if text else "")
    return [{"type": "text", "text": text[:15000] or "(no output)"}]
