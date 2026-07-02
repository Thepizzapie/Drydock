"""Git worktree helpers — one isolated working tree per run.

Every tier layers on a worktree: the agent edits `drydock/<key>` on a branch cut
from the ticket's base commit; review = diff vs base, then merge or discard.
Falls back to a plain copy-free dir when the repo isn't a git repo.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import config


def _git(root, *args, timeout=30):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, timeout=timeout)


def is_git_repo(root) -> bool:
    try:
        r = _git(root, "rev-parse", "--is-inside-work-tree")
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (OSError, subprocess.TimeoutExpired):
        return False


def head_commit(root) -> str | None:
    try:
        r = _git(root, "rev-parse", "HEAD")
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _worktrees_dir() -> Path:
    d = config.home() / "worktrees"
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_worktree(repo_root, branch, base_commit=None) -> tuple[str, str]:
    """Create a worktree at ~/.drydock/worktrees/<branch>. Returns (path, base_commit)."""
    base = base_commit or head_commit(repo_root) or "HEAD"
    safe = branch.replace("/", "-")
    path = _worktrees_dir() / safe
    if path.exists():
        # reuse if present
        return str(path), base
    r = _git(repo_root, "worktree", "add", "-b", branch, str(path), base)
    if r.returncode != 0:
        # branch may already exist — try without -b
        r2 = _git(repo_root, "worktree", "add", str(path), branch)
        if r2.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {r.stderr or r2.stderr}")
    return str(path), base


def diff(worktree_path, base_commit) -> str:
    try:
        # include unstaged + untracked by adding intent-to-add
        _git(worktree_path, "add", "-A", "-N")
        r = _git(worktree_path, "diff", base_commit or "HEAD")
        return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def merge_worktree(repo_root, branch, message) -> dict:
    """Commit everything in the worktree branch and merge it into the current branch."""
    safe = branch.replace("/", "-")
    wt = _worktrees_dir() / safe
    _git(wt, "add", "-A")
    commit = _git(wt, "commit", "-m", message)
    committed = commit.returncode == 0
    m = _git(repo_root, "merge", "--no-ff", branch, "-m", f"Merge {branch}: {message}")
    return {"committed": committed, "merged": m.returncode == 0,
            "detail": (m.stderr or m.stdout).strip()}


def remove_worktree(repo_root, branch, delete_branch=True) -> None:
    safe = branch.replace("/", "-")
    wt = _worktrees_dir() / safe
    _git(repo_root, "worktree", "remove", "--force", str(wt))
    if delete_branch:
        _git(repo_root, "branch", "-D", branch)
