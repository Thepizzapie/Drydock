"""Tiered embedding backends — never required, never blocking.

Order of preference:
  1. fastembed (``pip install drydock-ai[embeddings]``) — local ONNX, no server
  2. Ollama at localhost:11434 (autodetected) — nomic-embed-text
  3. none — recall runs FTS-only
"""
from __future__ import annotations

import functools
import json
import os
import urllib.error
import urllib.request

_OLLAMA = "http://127.0.0.1:11434"
_OLLAMA_MODEL = "nomic-embed-text"


@functools.lru_cache(maxsize=1)
def backend() -> str:
    if os.environ.get("DRYDOCK_NO_EMBED"):
        return "none"
    try:
        import fastembed  # noqa: F401
        return "fastembed"
    except ImportError:
        pass
    try:
        req = urllib.request.Request(_OLLAMA + "/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            models = json.loads(resp.read()).get("models", [])
        if any(_OLLAMA_MODEL in (m.get("name") or "") for m in models):
            return "ollama"
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        pass
    return "none"


def available() -> bool:
    return backend() != "none"


def embed(texts: list[str]) -> list[list[float]] | None:
    b = backend()
    if b == "fastembed":
        from fastembed import TextEmbedding
        model = _fastembed_model()
        return [list(v) for v in model.embed(texts)]
    if b == "ollama":
        out = []
        for t in texts:
            body = json.dumps({"model": _OLLAMA_MODEL, "prompt": t}).encode()
            req = urllib.request.Request(
                _OLLAMA + "/api/embeddings", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                out.append(json.loads(resp.read())["embedding"])
        return out
    return None


@functools.lru_cache(maxsize=1)
def _fastembed_model():
    from fastembed import TextEmbedding
    return TextEmbedding("BAAI/bge-small-en-v1.5")
