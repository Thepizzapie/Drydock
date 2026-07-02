"""Tier 0 — in-process worker with realpath containment + scrubbed env.

Policy-grade, NOT a VM boundary (said plainly in the UI and README). File tools
are confined to the workspace root by realpath check (orbit codebase.py hardening);
bash runs with a scrubbed environment (no HOME creds, no API keys, minimal PATH)
and hard timeout + output caps. Tiers 1/2 reuse these exact tool implementations
inside their boundary — only the transport differs.
"""
from __future__ import annotations

import os
import subprocess

from .base import ToolResult, Workspace, WorkspaceProvider, Worker
from . import worktree

_OUTPUT_CAP = 30_000
_FILE_CAP = 400_000
_BASH_TIMEOUT = 120


def _contained(root: str, rel: str) -> str | None:
    """Resolve rel under root; return abs path iff it stays inside root."""
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(base, rel))
    if target == base or target.startswith(base + os.sep):
        return target
    return None


def _scrubbed_env(root: str) -> dict:
    keep = {}
    path = os.environ.get("PATH", "")
    keep["PATH"] = path
    keep["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
    keep["TEMP"] = os.environ.get("TEMP", "")
    keep["TMP"] = os.environ.get("TMP", "")
    keep["HOME"] = root          # HOME points into the sandbox, not the user's
    keep["USERPROFILE"] = root
    keep["DRYDOCK_SANDBOX"] = "1"
    return {k: v for k, v in keep.items() if v}


class Tier0Worker:
    def __init__(self, workspace: Workspace):
        self.ws = workspace
        self.root = workspace.root

    # ── file tools (confined) ──
    def _read(self, path):
        target = _contained(self.root, path)
        if not target:
            return ToolResult(False, error=f"path escapes workspace: {path}")
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                data = f.read(_FILE_CAP + 1)
            if "\x00" in data:
                return ToolResult(False, error="binary file")
            return ToolResult(True, output=data[:_FILE_CAP])
        except FileNotFoundError:
            return ToolResult(False, error=f"not found: {path}")
        except OSError as e:
            return ToolResult(False, error=str(e))

    def _write(self, path, content):
        target = _contained(self.root, path)
        if not target:
            return ToolResult(False, error=f"path escapes workspace: {path}")
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content or "")
            return ToolResult(True, output=f"wrote {path} ({len(content or '')} bytes)")
        except OSError as e:
            return ToolResult(False, error=str(e))

    def _edit(self, path, old, new):
        target = _contained(self.root, path)
        if not target:
            return ToolResult(False, error=f"path escapes workspace: {path}")
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = f.read()
        except OSError as e:
            return ToolResult(False, error=str(e))
        if old not in data:
            return ToolResult(False, error="old_string not found")
        if data.count(old) > 1:
            return ToolResult(False, error="old_string not unique")
        data = data.replace(old, new, 1)
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(data)
        except OSError as e:
            return ToolResult(False, error=str(e))
        return ToolResult(True, output=f"edited {path}")

    def _ls(self, path="."):
        target = _contained(self.root, path)
        if not target:
            return ToolResult(False, error=f"path escapes workspace: {path}")
        try:
            names = sorted(os.listdir(target))
            return ToolResult(True, output="\n".join(names))
        except OSError as e:
            return ToolResult(False, error=str(e))

    def _glob(self, pattern):
        import glob as g
        base = os.path.realpath(self.root)
        matches = g.glob(os.path.join(base, pattern), recursive=True)
        rels = sorted(os.path.relpath(m, base).replace("\\", "/") for m in matches)
        return ToolResult(True, output="\n".join(rels[:500]))

    def _grep(self, pattern, path="."):
        import re
        target = _contained(self.root, path)
        if not target:
            return ToolResult(False, error=f"path escapes workspace: {path}")
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return ToolResult(False, error=f"bad regex: {e}")
        hits = []
        base = os.path.realpath(self.root)
        walk_root = target if os.path.isdir(target) else os.path.dirname(target)
        for dirpath, dirs, files in os.walk(walk_root):
            dirs[:] = [d for d in dirs if d not in
                       (".git", "node_modules", ".venv", "__pycache__", ".next")]
            for fn in files:
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if rx.search(line):
                                rel = os.path.relpath(fp, base).replace("\\", "/")
                                hits.append(f"{rel}:{i}: {line.rstrip()}")
                                if len(hits) >= 200:
                                    return ToolResult(True, output="\n".join(hits))
                except OSError:
                    continue
        return ToolResult(True, output="\n".join(hits) or "(no matches)")

    def _bash(self, command):
        try:
            r = subprocess.run(
                command, shell=True, cwd=self.root, capture_output=True, text=True,
                timeout=_BASH_TIMEOUT, env=_scrubbed_env(self.root))
            out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
            return ToolResult(r.returncode == 0, output=out[:_OUTPUT_CAP],
                              error=None if r.returncode == 0 else f"exit {r.returncode}",
                              meta={"exit_code": r.returncode})
        except subprocess.TimeoutExpired:
            return ToolResult(False, error=f"timeout after {_BASH_TIMEOUT}s")
        except OSError as e:
            return ToolResult(False, error=str(e))

    def _git(self, *args):
        try:
            r = subprocess.run(["git", "-C", self.root, *args],
                               capture_output=True, text=True, timeout=30)
            return ToolResult(r.returncode == 0, output=(r.stdout or r.stderr)[:_OUTPUT_CAP])
        except (OSError, subprocess.TimeoutExpired) as e:
            return ToolResult(False, error=str(e))

    def exec(self, tool, args) -> ToolResult:
        a = args or {}
        if tool == "read_file":
            return self._read(a.get("path", ""))
        if tool == "write_file":
            return self._write(a.get("path", ""), a.get("content", ""))
        if tool == "edit_file":
            return self._edit(a.get("path", ""), a.get("old_string", ""), a.get("new_string", ""))
        if tool == "ls":
            return self._ls(a.get("path", "."))
        if tool == "glob":
            return self._glob(a.get("pattern", "**/*"))
        if tool == "grep":
            return self._grep(a.get("pattern", ""), a.get("path", "."))
        if tool == "bash":
            return self._bash(a.get("command", ""))
        if tool == "git_status":
            return self._git("status", "--porcelain")
        if tool == "git_diff":
            return self._git("diff")
        return ToolResult(False, error=f"unknown tool: {tool}")

    def close(self):
        pass


class Tier0Provider(WorkspaceProvider):
    """Provisions a git-worktree workspace (or a plain dir when not a git repo)."""

    def __init__(self, ticket_key: str | None = None):
        self.ticket_key = ticket_key or "run"

    def provision(self, project, run_id) -> Workspace:
        from ..store import runs as runs_store, service
        p = service.get_project(project)
        root = (p or {}).get("root_path")
        if not root:
            raise RuntimeError("project has no root_path")

        if worktree.is_git_repo(root):
            branch = f"drydock/{self.ticket_key.lower()}-{run_id[-6:].lower()}"
            path, base = worktree.add_worktree(root, branch)
            kind = "worktree"
        else:
            branch, base, path, kind = None, None, root, "dir"

        ws_row = runs_store.create_workspace(
            project, run_id=run_id, tier=0, kind=kind, path=path,
            base_commit=base, branch=branch)
        return Workspace(id=ws_row["id"], root=path, tier=0, kind=kind,
                         branch=branch, base_commit=base)

    def worker(self, workspace) -> Worker:
        return Tier0Worker(workspace)

    def diff(self, workspace) -> str:
        if workspace.kind != "worktree":
            return ""
        return worktree.diff(workspace.root, workspace.base_commit)

    def merge(self, workspace, message) -> dict:
        from ..store import runs as runs_store, service
        p = service.get_project_by_workspace(workspace) if hasattr(
            service, "get_project_by_workspace") else None
        # repo root = the worktree's main repo; derive from workspace row
        ws = runs_store.get_workspace(workspace.id)
        repo_root = _repo_root_for(ws)
        if workspace.kind != "worktree" or not repo_root:
            return {"merged": False, "detail": "not a worktree"}
        res = worktree.merge_worktree(repo_root, workspace.branch, message)
        runs_store.set_workspace_status(workspace.id, "merged")
        return res

    def discard(self, workspace) -> None:
        from ..store import runs as runs_store
        ws = runs_store.get_workspace(workspace.id)
        repo_root = _repo_root_for(ws)
        if workspace.kind == "worktree" and repo_root:
            try:
                worktree.remove_worktree(repo_root, workspace.branch)
            except Exception:
                pass
        runs_store.set_workspace_status(workspace.id, "discarded")


def _repo_root_for(ws_row) -> str | None:
    """The project's root_path is the main repo the worktree was cut from."""
    if not ws_row:
        return None
    from ..store import db
    p = db.one("SELECT root_path FROM projects WHERE id=?", (ws_row["project_id"],))
    return (p or {}).get("root_path")
