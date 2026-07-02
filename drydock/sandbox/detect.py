"""Environment detection for the first-run wizard and tier badge."""
from __future__ import annotations

import functools
import shutil
import subprocess


def _ok(cmd, timeout=10) -> bool:
    exe = cmd[0]
    if not shutil.which(exe):
        return False
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@functools.lru_cache(maxsize=1)
def wsl_available() -> bool:
    return _ok(["wsl", "--status"])


@functools.lru_cache(maxsize=1)
def docker_available() -> bool:
    return _ok(["docker", "info", "--format", "{{.ServerVersion}}"])


def git_available() -> bool:
    return shutil.which("git") is not None


def recommended_tier() -> int:
    if wsl_available():
        return 1
    if docker_available():
        return 2
    return 0


def tiers() -> dict:
    return {
        "recommended": recommended_tier(),
        "available": {
            0: True,
            1: wsl_available(),
            2: docker_available(),
        },
        "labels": {
            0: "Policy-only (no VM boundary)",
            1: "WSL2 VM boundary",
            2: "Docker container",
        },
    }
