"""`drydock hooks install` — route external agents' policy decisions into Drydock.

Reuses aegis's Claude Code hook surface, but points the audit sink at the project's
drydock.db (audit.ext_session_id) so Claude Code / Codex sessions running on this
machine show up in Mission Control (blame, rap sheet, token attribution) and their
permission prompts can land in the same approval queue.

This writes a hooks block into <repo>/.claude/settings.json that invokes
`drydock hookcapture <event>`, which normalizes the payload and records it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_CAPTURE_EVENTS = ["PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop", "SessionEnd"]


def install(repo_root: str, project_slug: str) -> dict:
    settings = Path(repo_root) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    hooks = data.setdefault("hooks", {})
    cmd = f'drydock hookcapture --project {project_slug}'
    for ev in _CAPTURE_EVENTS:
        entry = {"hooks": [{"type": "command", "command": f'{cmd} {ev}'}]}
        # don't clobber existing non-drydock hooks; append if ours isn't there
        arr = hooks.setdefault(ev, [])
        if not any("drydock hookcapture" in h.get("command", "")
                   for e in arr for h in e.get("hooks", [])):
            arr.append(entry)
    settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"settings": str(settings), "events": _CAPTURE_EVENTS}


def capture(project_slug: str, event: str) -> int:
    """Read a Claude Code hook payload on stdin, record it into audit/events.

    Exit 0 always (a capture hook must never break the host session). If aegis is
    installed it can additionally evaluate policy; here we default to observe-only.
    """
    from ..store import runs as runs_store, service

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        payload = {}

    try:
        service._pid(project_slug)  # validate project exists
    except ValueError:
        return 0

    tool = payload.get("tool_name") or payload.get("tool")
    session_id = payload.get("session_id")
    tool_input = payload.get("tool_input") or {}

    # observe-only sink: record the external action as an allow in the shared audit
    try:
        runs_store.add_audit(
            decision="allow", event=event, tool=tool,
            action=_classify(tool), args=tool_input,
            identity=f"external:{session_id or '?'}",
            ext_session_id=session_id)
    except Exception:
        pass
    return 0


def _classify(tool):
    t = (tool or "").lower()
    if t in ("read", "glob", "grep", "ls"):
        return "read"
    if t in ("write",):
        return "write"
    if t in ("edit", "multiedit"):
        return "edit"
    if t in ("bash", "powershell"):
        return "shell"
    return "other"
