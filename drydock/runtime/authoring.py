"""Author agents from the dashboard — the OpenCode "build your own agent" surface.

A spec (name, description, model, tools, permission rules, system prompt) becomes
a real Markdown agent file: written to `.drydock/agents/<name>.md` in the repo (so
it's version-controllable and CLI-editable) AND registered in the store. The model
can be a cloud model or any locally-served one — Drydock routes it either way.
"""
from __future__ import annotations

import re

from ..store import service
from . import agentdef, tools as tools_mod

_SAFE_NAME = re.compile(r"[^a-z0-9_-]+")


def tool_catalog() -> list[dict]:
    """The tools an agent can be granted, for the authoring UI."""
    return [{"name": n, "description": s["description"]}
            for n, s in tools_mod.TOOL_SCHEMAS.items() if n != "task_done"]


def _slug(name: str) -> str:
    return _SAFE_NAME.sub("-", (name or "agent").lower()).strip("-") or "agent"


def build_markdown(spec: dict) -> str:
    import yaml

    name = spec.get("name") or "agent"
    fm = {
        "name": name,
        "description": spec.get("description", ""),
        "model": spec.get("model"),
        "tools": spec.get("tools") or list(agentdef.DEFAULT_TOOLS),
        "max_turns": int(spec.get("max_turns", 50)),
        "permissions": spec.get("permissions") or {"default": "deny", "rules": []},
    }
    front = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).strip()
    body = (spec.get("system_prompt") or "").strip() or f"# {name}\n\nDescribe how {name} should work."
    return f"---\n{front}\n---\n\n{body}\n"


def author_agent(project: str, spec: dict) -> dict:
    if not (spec.get("name") or "").strip():
        raise ValueError("agent name is required")
    md = build_markdown(spec)
    ad = agentdef.parse(md)

    # persist to the repo as a real, editable agent file when a repo path exists
    p = service.get_project(project)
    root = (p or {}).get("root_path")
    written = None
    if root:
        from .. import config
        agents_dir = config.project_dir(root) / "agents"
        try:
            agents_dir.mkdir(parents=True, exist_ok=True)
            path = agents_dir / f"{_slug(ad.name)}.md"
            path.write_text(md, encoding="utf-8")
            written = str(path)
        except OSError:
            pass

    row = agentdef.register(project, ad, definition_md=md)
    row["_file"] = written
    return row
