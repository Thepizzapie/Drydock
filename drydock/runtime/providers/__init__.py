"""Model providers. Anthropic first + an OpenAI-compatible client + a test mock."""
from __future__ import annotations


def get_provider(name: str, model: str | None = None):
    if name == "mock":
        from .mock import MockProvider
        return MockProvider(model)
    if name in ("anthropic", "claude"):
        from .anthropic import AnthropicProvider
        return AnthropicProvider(model)
    if name in ("openai", "openai_compat", "ollama"):
        from .openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(model)
    raise ValueError(f"unknown provider: {name}")
