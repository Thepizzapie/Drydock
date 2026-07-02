"""Model catalog — cloud models + locally-served models, for the UI + authoring.

Local support is the point of the product: a dev can build an agent that runs on
a model on their own machine (Ollama / LM Studio / any OpenAI-compatible server)
and still get the full sandbox + policy + tools. This module surfaces what's
actually reachable so the dashboard can offer it.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import pricing

# Known cloud models we price + offer by default.
CLOUD_MODELS = [
    {"id": "claude-fable-5", "label": "Claude Fable 5", "vendor": "anthropic"},
    {"id": "claude-opus-4-8", "label": "Claude Opus 4.8", "vendor": "anthropic"},
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5", "vendor": "anthropic"},
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5", "vendor": "anthropic"},
]


def _openai_base() -> str:
    return os.environ.get("DRYDOCK_OPENAI_BASE", "http://127.0.0.1:11434/v1")


def _ollama_base() -> str:
    # the OpenAI-compat base for Ollama ends in /v1; the native tags API doesn't
    base = _openai_base()
    return base[:-3] if base.endswith("/v1") else base


def local_models() -> dict:
    """Detect an OpenAI-compatible local server and list its models.

    Tries the OpenAI-compat /models endpoint first, then Ollama's native /api/tags.
    Returns {endpoint, available, models:[{id,label}]}.
    """
    endpoint = _openai_base()
    # 1) OpenAI-compatible /models
    try:
        req = urllib.request.Request(endpoint.rstrip("/") + "/models")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read())
        ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        if ids:
            return {"endpoint": endpoint, "available": True,
                    "models": [{"id": i, "label": i} for i in sorted(ids)]}
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError, ValueError):
        pass
    # 2) Ollama native /api/tags
    try:
        req = urllib.request.Request(_ollama_base().rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read())
        names = [m.get("name") for m in data.get("models", []) if m.get("name")]
        if names:
            return {"endpoint": endpoint, "available": True,
                    "models": [{"id": n, "label": n} for n in sorted(names)]}
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError, ValueError):
        pass
    return {"endpoint": endpoint, "available": False, "models": []}


def catalog() -> dict:
    """Everything the UI needs to offer a model: cloud + detected local."""
    local = local_models()
    for m in local["models"]:
        m["local"] = True
        m["cost"] = "free"
    cloud = []
    for m in CLOUD_MODELS:
        r = pricing.rates(m["id"])
        cloud.append({**m, "local": False,
                      "cost": f"${r[0] / 10:.2f}/${r[1] / 10:.2f} per 1M in/out" if r else "—"})
    return {"cloud": cloud, "local": local}
