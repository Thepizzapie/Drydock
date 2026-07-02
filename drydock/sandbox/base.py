"""Sandbox protocols.

A run needs two things from a sandbox:
  - a Workspace: an isolated copy of the repo the agent edits (git worktree, dir,
    wsl dir, or container mount)
  - a Worker: something that executes a tool call *inside* that isolation and
    returns a result. Tier 0 runs the worker in-process; tiers 1/2 run it across
    a WSL/container boundary via JSON-RPC over stdio (same ToolResult shape).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolResult:
    ok: bool
    output: str = ""
    error: str | None = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "output": self.output, "error": self.error, "meta": self.meta}


@dataclass
class Workspace:
    id: str
    root: str            # absolute path the worker treats as its world
    tier: int
    kind: str            # worktree | dir | wsl | container
    branch: str | None = None
    base_commit: str | None = None
    meta: dict = field(default_factory=dict)


class Worker(Protocol):
    def exec(self, tool: str, args: dict) -> ToolResult: ...
    def close(self) -> None: ...


class WorkspaceProvider(Protocol):
    def provision(self, project, run_id) -> Workspace: ...
    def worker(self, workspace: Workspace) -> Worker: ...
    def merge(self, workspace: Workspace, message: str) -> dict: ...
    def discard(self, workspace: Workspace) -> None: ...
    def diff(self, workspace: Workspace) -> str: ...
