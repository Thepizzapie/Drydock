"""Provider contract — normalized so the session loop is provider-agnostic.

A provider turns (system, messages, tools) into a Turn: assistant text plus any
tool calls, plus token usage. Messages use a small internal shape the loop owns;
each provider translates to/from its wire format.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    text: str = ""
    tool_calls: list = field(default_factory=list)   # list[ToolCall]
    stop_reason: str = "end_turn"                    # end_turn | tool_use | max_tokens
    tokens_in: int = 0
    tokens_out: int = 0


class Provider:
    def complete(self, system: str, messages: list, tools: list) -> Turn:
        raise NotImplementedError
