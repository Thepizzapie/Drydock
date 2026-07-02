"""Anthropic provider. Lazy-imports the SDK so the package stays optional."""
from __future__ import annotations

import os

from .. import pricing
from .base import Provider, ToolCall, Turn

_DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicProvider(Provider):
    def __init__(self, model=None):
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic SDK not installed — `pip install drydock-ai[runtime]`") from e
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model or _DEFAULT_MODEL

    def complete(self, system, messages, tools) -> Turn:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=tools or [],
        )
        text_parts, calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, dict(block.input or {})))
        return Turn(
            text="\n".join(text_parts),
            tool_calls=calls,
            stop_reason=resp.stop_reason or "end_turn",
            tokens_in=resp.usage.input_tokens,
            tokens_out=resp.usage.output_tokens,
        )

    def cost_cents(self, tokens_in, tokens_out) -> int:
        return pricing.cost_cents(self.model, tokens_in, tokens_out)
