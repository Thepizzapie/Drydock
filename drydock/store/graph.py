"""File context — minimal v1 of orbit ``graph.py`` file_context.

Returns for a scoped path: graph presence, connected files (live edges), recent
commits (git, fail-safe), and a capped content head. All filesystem reads are
realpath-contained inside the project root (orbit codebase.py hardening).
"""
from __future__ import annotations

import os
import subprocess

from . import db, service

_CONTENT_CAP = 1200


def _contained_read(root: str, rel_path: str) -> str | None:
    """Read a file iff its real path stays inside root. None otherwise."""
    if not root:
        return None
    base = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(base, rel_path))
    if not (candidate == base or candidate.startswith(base + os.sep)):
        return None
    try:
        with open(candidate, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(_CONTENT_CAP + 1)
        # binary sniff
        if "\x00" in head:
            return None
        return head[:_CONTENT_CAP]
    except OSError:
        return None


def _recent_commits(root: str, rel_path: str, n: int = 2) -> list[str]:
    if not root:
        return []
    try:
        out = subprocess.run(
            ["git", "-C", root, "log", f"-{n}", "--format=%h %s", "--", rel_path],
            capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return []
        return [l for l in out.stdout.splitlines() if l.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def file_context(project, path: str) -> dict:
    pid = service._pid(project)
    p = service.get_project(project)
    root = (p or {}).get("root_path")

    ent = db.one(
        "SELECT id FROM entities WHERE project_id=? AND kind='file' AND name=?",
        (pid, path))

    connected: list[str] = []
    if ent:
        rows = db.q(
            """SELECT e2.name AS name
               FROM relationships r
               JOIN entities e2
                 ON e2.id = CASE WHEN r.src_id=? THEN r.dst_id ELSE r.src_id END
               WHERE r.project_id=? AND r.valid_to IS NULL
                 AND r.relation IN ('co_changed','mentions','part_of')
                 AND (r.src_id=? OR r.dst_id=?)
                 AND e2.kind='file'""",
            (ent["id"], pid, ent["id"], ent["id"]))
        connected = [r["name"] for r in rows if r["name"] != path][:6]

    content = _contained_read(root, path)
    return {
        "path": path,
        "found": ent is not None or content is not None,
        "connected_files": connected,
        "recent_commits": _recent_commits(root, path),
        "content": content,
    }
