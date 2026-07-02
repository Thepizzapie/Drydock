"""Policy kernel — the in-process aegis gate every tool call passes through.

The model can only emit tool JSON; the toolbus is the sole execution path and it
calls ``check()`` first. The kernel is never reachable from sandboxed code.

Policy layering (highest precedence first), assembled into a single aegis Policy:
    1. aegis built-in rules (non-escapable; live inside engine.evaluate)
    2. project policy.yaml rules
    3. agent frontmatter rules (compiled)
    4. accumulated policy_grants ("always allow" answers) -> allow rules
The agent's default-deny rule sits at the bottom, so anything unmatched is denied.
"""
from __future__ import annotations

from dataclasses import dataclass

_UNAVAILABLE = None


def aegis_available() -> bool:
    try:
        import aegis  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class Verdict:
    decision: str          # allow | deny | ask
    rule: str | None
    message: str | None


# tool -> aegis ActionClass value
_TOOL_ACTION = {
    "read_file": "read", "ls": "read", "glob": "read", "grep": "read",
    "git_status": "read", "git_diff": "read",
    "write_file": "write", "edit_file": "edit",
    "bash": "shell", "network": "net", "task_done": "other",
}


def _normalize_args(tool: str, args: dict) -> dict:
    """Translate Drydock's natural tool arg names into aegis's vocabulary.

    aegis rules and built-in guards key on `file_path` / `command` (Claude Code's
    tool arg names). Our schemas use `path`. We add the aegis-standard keys so
    both agent frontmatter rules and aegis built-ins match, while the sandbox
    worker still receives the original names.
    """
    out = dict(args)
    if "path" in out and "file_path" not in out:
        out["file_path"] = out["path"]
    return out


class Kernel:
    """Holds the assembled Policy for one run and evaluates each tool call."""

    def __init__(self, project, agentdef, workspace_root=None, identity=None):
        self.project = project
        self.agentdef = agentdef
        self.workspace_root = workspace_root
        self.identity = identity
        self._policy = self._build_policy()

    def _build_policy(self):
        if not aegis_available():
            return None
        from aegis.loader import load_policy
        from aegis.policy import Action, Policy, Rule

        from .. import config
        from ..store import runs as runs_store, service

        # 1. project policy.yaml (aegis built-ins are applied by engine.evaluate)
        policy = Policy(default_action=Action.ALLOW)
        p = service.get_project(self.project)
        root = (p or {}).get("root_path")
        if root:
            pol_file = config.project_dir(root) / "policy.yaml"
            if pol_file.exists():
                try:
                    policy = load_policy(pol_file)
                except Exception:
                    policy = Policy(default_action=Action.ALLOW)

        # 2. accumulated grants -> allow rules (higher priority than agent rules)
        grant_rules = []
        try:
            for g in runs_store.list_grants(self.project):
                scope = g.get("scope") or {}
                grant_rules.append(Rule(
                    name=f"grant:{g['rule']}",
                    action=Action.ALLOW,
                    actions=[scope["action_class"]] if scope.get("action_class") else [],
                    argument_patterns={"file_path": scope["file_path"]} if scope.get("file_path") else {},
                    priority=500,
                ))
        except Exception:
            pass

        # 3. agent frontmatter rules
        from . import agentdef as agentdef_mod
        agent_rules = agentdef_mod.compile_rules(self.agentdef)

        policy.rules = list(policy.rules) + grant_rules + agent_rules
        return policy

    def check(self, tool: str, args: dict) -> Verdict:
        """Evaluate one tool call. Fail-open on internal error (matches aegis posture)."""
        if self._policy is None:
            return Verdict("allow", None, None)  # no aegis installed -> tool confinement only
        from aegis.engine import safe_evaluate
        from aegis.events import ActionClass, Event

        ev = Event.make(
            "PreToolUse",
            tool=tool,
            action=ActionClass(_TOOL_ACTION.get(tool, "other")),
            args=_normalize_args(tool, args or {}),
            identity=self.identity,
            cwd=self.workspace_root,
        )
        d = safe_evaluate(ev, self._policy)
        return Verdict(d.action.value, d.rule, d.message)

    def rebuild(self):
        """Re-assemble the policy (call after a new grant is added)."""
        self._policy = self._build_policy()
