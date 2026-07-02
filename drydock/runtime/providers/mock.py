"""Scriptable provider for tests and offline runs.

Feed it a program: a list of Turns to emit in order. Lets the whole session loop
+ toolbus + sandbox + kernel be verified without a network or API key.
"""
from __future__ import annotations

from .base import Provider, ToolCall, Turn


class MockProvider(Provider):
    def __init__(self, model=None, program=None):
        self.model = model or "mock"
        self.program = list(program or [])
        self._i = 0

    def script(self, turns):
        self.program = list(turns)
        self._i = 0
        return self

    def complete(self, system, messages, tools) -> Turn:
        if self._i < len(self.program):
            turn = self.program[self._i]
            self._i += 1
            return turn
        # default terminal turn if the program runs out
        return Turn(text="done", tool_calls=[ToolCall("final", "task_done",
                    {"summary": "completed"})], stop_reason="tool_use",
                    tokens_in=10, tokens_out=5)


def call(name, args, id="c"):
    return ToolCall(id, name, args)


def turn(text="", calls=None, tokens_in=20, tokens_out=10):
    tc = calls or []
    return Turn(text=text, tool_calls=tc,
                stop_reason="tool_use" if tc else "end_turn",
                tokens_in=tokens_in, tokens_out=tokens_out)
