"""OpenAI-compatible provider (covers local Ollama, LM Studio, vLLM, etc.).

Uses the OpenAI SDK if present; base URL from DRYDOCK_OPENAI_BASE (default Ollama).
Translates our internal messages to Chat Completions tool-calling and back.
"""
from __future__ import annotations

import json
import os

from .base import Provider, ToolCall, Turn


class OpenAICompatProvider(Provider):
    def __init__(self, model=None):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("openai SDK not installed — `pip install openai`") from e
        base = os.environ.get("DRYDOCK_OPENAI_BASE", "http://127.0.0.1:11434/v1")
        key = os.environ.get("DRYDOCK_OPENAI_KEY", "ollama")
        self._client = OpenAI(base_url=base, api_key=key)
        self.model = model or os.environ.get("DRYDOCK_OPENAI_MODEL", "qwen2.5-coder")

    def complete(self, system, messages, tools) -> Turn:
        oai_tools = [{"type": "function",
                      "function": {"name": t["name"], "description": t["description"],
                                   "parameters": t["input_schema"]}} for t in (tools or [])]
        oai_msgs = [{"role": "system", "content": system}] + _to_openai(messages)
        resp = self._client.chat.completions.create(
            model=self.model, messages=oai_msgs,
            tools=oai_tools or None, max_tokens=4096)
        choice = resp.choices[0].message
        calls = []
        for tc in (choice.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc.id, tc.function.name, args))
        usage = resp.usage
        return Turn(
            text=choice.content or "",
            tool_calls=calls,
            stop_reason="tool_use" if calls else "end_turn",
            tokens_in=getattr(usage, "prompt_tokens", 0),
            tokens_out=getattr(usage, "completion_tokens", 0),
        )

    def cost_cents(self, tokens_in, tokens_out) -> int:
        return 0  # local models are free


def _to_openai(messages):
    """Translate internal message shape -> OpenAI chat messages."""
    out = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        # content is a list of blocks (text / tool_use / tool_result)
        text_bits, tool_calls, tool_results = [], [], []
        for b in content:
            if b.get("type") == "text":
                text_bits.append(b["text"])
            elif b.get("type") == "tool_use":
                tool_calls.append({
                    "id": b["id"], "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b["input"])}})
            elif b.get("type") == "tool_result":
                tool_results.append(b)
        if role == "assistant":
            msg = {"role": "assistant", "content": "\n".join(text_bits) or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
        else:
            if tool_results:
                for tr in tool_results:
                    out.append({"role": "tool", "tool_call_id": tr["tool_use_id"],
                                "content": _result_text(tr["content"])})
            if text_bits:
                out.append({"role": "user", "content": "\n".join(text_bits)})
    return out


def _result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)
