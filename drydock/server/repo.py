"""Repo introspection for the dashboard — branch, changes, history, contained file browsing.

All reads are fail-safe (a project without git just returns empty lists) and all
file access is realpath-contained inside the project root (orbit codebase.py rule).
"""
from __future__ import annotations

import os
import subprocess

_IGNORE_DIRS = {".git", ".venv", "venv", "node_modules", ".next", "__pycache__",
                "dist", "build", ".drydock", ".turbo", "out"}
_FILE_CAP = 120_000


def _git(root, *args, timeout=10):
    try:
        return subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def summary(root: str) -> dict:
    if not root or not os.path.isdir(root):
        return {"is_git": False, "branch": None, "changes": [], "commits": []}

    branch = None
    r = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if r and r.returncode == 0:
        branch = r.stdout.strip()

    changes = []
    r = _git(root, "status", "--porcelain")
    if r and r.returncode == 0:
        for line in r.stdout.splitlines():
            if len(line) > 3:
                changes.append({"status": line[:2].strip() or "??", "path": line[3:].strip()})

    commits = []
    r = _git(root, "log", "-25", "--format=%h%x1f%s%x1f%an%x1f%aI")
    if r and r.returncode == 0:
        for line in r.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append({"sha": parts[0], "message": parts[1],
                                "author": parts[2], "when": parts[3]})

    return {"is_git": branch is not None, "branch": branch,
            "changes": changes, "commits": commits}


def commit_detail(root: str, sha: str) -> dict:
    if not sha.replace("-", "").isalnum() or len(sha) > 64:
        return {"files": []}
    r = _git(root, "show", "--stat", "--format=%h %s%n%an · %aI", sha)
    return {"text": r.stdout[:20_000] if r and r.returncode == 0 else ""}


def _contained(root: str, rel: str) -> str | None:
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(base, rel or "."))
    if target == base or target.startswith(base + os.sep):
        return target
    return None


def list_dir(root: str, rel: str = "") -> dict:
    target = _contained(root, rel)
    if not target or not os.path.isdir(target):
        return {"path": rel, "dirs": [], "files": []}
    dirs, files = [], []
    try:
        for name in sorted(os.listdir(target)):
            full = os.path.join(target, name)
            if os.path.isdir(full):
                if name not in _IGNORE_DIRS and not name.startswith("."):
                    dirs.append(name)
            else:
                try:
                    files.append({"name": name, "size": os.path.getsize(full)})
                except OSError:
                    files.append({"name": name, "size": 0})
    except OSError:
        pass
    return {"path": rel, "dirs": dirs, "files": files}


def read_file(root: str, rel: str) -> dict:
    target = _contained(root, rel)
    if not target or not os.path.isfile(target):
        return {"path": rel, "found": False, "content": None}
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(_FILE_CAP + 1)
    except OSError:
        return {"path": rel, "found": False, "content": None}
    if "\x00" in content:
        return {"path": rel, "found": True, "binary": True, "content": None}
    truncated = len(content) > _FILE_CAP
    return {"path": rel, "found": True, "binary": False,
            "content": content[:_FILE_CAP], "truncated": truncated}
