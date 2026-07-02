"""Path and settings resolution.

Data home (all mutable state):
    $DRYDOCK_HOME  >  ~/.drydock/

Layout:
    ~/.drydock/drydock.db        SQLite (WAL) — system of record
    ~/.drydock/chroma/           embedded vector store (optional)
    ~/.drydock/keys/             aegis identity keys (Phase 1)
    ~/.drydock/settings.json     global settings

Per-repo (created by `drydock init`):
    .drydock/policy.yaml         project policy (aegis-shaped)
    .drydock/agents/*.md         agent definitions
    .drydock/settings.json       project-local overrides
"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "drydock"


def home() -> Path:
    env = os.environ.get("DRYDOCK_HOME")
    p = Path(env) if env else Path.home() / ".drydock"
    return p


def db_path() -> Path:
    return home() / "drydock.db"


def chroma_dir() -> Path:
    return home() / "chroma"


def keys_dir() -> Path:
    return home() / "keys"


def ensure_home() -> Path:
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    return h


def settings_path() -> Path:
    return home() / "settings.json"


def load_settings() -> dict:
    p = settings_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_settings(settings: dict) -> None:
    ensure_home()
    settings_path().write_text(
        json.dumps(settings, indent=2), encoding="utf-8"
    )


def project_dir(repo_root: str | Path) -> Path:
    """Per-repo .drydock/ directory."""
    return Path(repo_root) / ".drydock"
