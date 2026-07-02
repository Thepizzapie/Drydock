"""Agent definitions: markdown + YAML frontmatter → registry + compiled policy.

Frontmatter (everything not declared is denied by the agent's own default):

    ---
    name: refactor-bot
    description: Small, safe refactors
    model: claude-sonnet-5
    tools: [read_file, edit_file, grep, glob, bash, git_diff, task_done]
    max_turns: 60
    budget: {tokens: 200000, cost_usd: 3.00}
    permissions:
      default: deny
      rules:
        - {action: read_file, scope: "ws://**", decision: allow}
        - {action: edit_file, scope: "ws://src/**", decision: allow}
        - {action: bash, match: "npm test*", decision: allow}
        - {action: network, scope: "*", decision: ask}
    ---
    # System prompt body…

`permissions` compiles into aegis Rule objects (aegis.policy.Rule). Layering is
applied in kernel.py: aegis built-ins > project policy.yaml > these agent rules >
accumulated policy_grants.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# tool name -> aegis ActionClass value (aegis.events.ActionClass)
_TOOL_ACTION = {
    "read_file": "read", "ls": "read", "glob": "read", "grep": "read",
    "git_status": "read", "git_diff": "read",
    "write_file": "write",
    "edit_file": "edit",
    "bash": "shell",
    "network": "net",
    "task_done": "other",
}

DEFAULT_TOOLS = ["read_file", "write_file", "edit_file", "ls", "glob", "grep",
                 "bash", "git_status", "git_diff", "task_done"]


@dataclass
class AgentDef:
    name: str
    description: str = ""
    model: str | None = None
    tools: list = field(default_factory=lambda: list(DEFAULT_TOOLS))
    max_turns: int = 50
    budget: dict = field(default_factory=dict)     # {tokens, cost_usd}
    permissions: dict = field(default_factory=dict)  # {default, rules:[...]}
    system_prompt: str = ""
    raw_frontmatter: dict = field(default_factory=dict)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    import yaml
    text = text.lstrip("﻿").lstrip()   # tolerate a UTF-8 BOM (Windows editors)
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        fm = {}
    return (fm if isinstance(fm, dict) else {}), parts[2].strip()


def parse(text: str) -> AgentDef:
    fm, body = _split_frontmatter(text)
    return AgentDef(
        name=fm.get("name") or "agent",
        description=fm.get("description") or "",
        model=fm.get("model"),
        tools=fm.get("tools") or list(DEFAULT_TOOLS),
        max_turns=int(fm.get("max_turns") or 50),
        budget=fm.get("budget") or {},
        permissions=fm.get("permissions") or {},
        system_prompt=body,
        raw_frontmatter=fm,
    )


def load_file(path: str | Path) -> AgentDef:
    return parse(Path(path).read_text(encoding="utf-8"))


def compile_rules(agentdef: AgentDef):
    """Compile the agent's `permissions` block into aegis Rule objects.

    Each frontmatter rule -> one aegis Rule. `scope: ws://src/**` becomes a
    file_path argument glob; `match:` becomes a command regex; `decision:` maps
    to the aegis Action. Priorities descend by declaration order so earlier rules
    win, and a final default rule enforces the agent's `default` (deny).
    """
    from aegis.policy import Action, Rule

    perms = agentdef.permissions or {}
    rules = []
    base_priority = 100
    for i, r in enumerate(perms.get("rules") or []):
        action_tool = r.get("action")            # our tool name or a bare class
        decision = (r.get("decision") or "deny").lower()
        act = {"allow": Action.ALLOW, "deny": Action.DENY, "ask": Action.ASK}.get(
            decision, Action.DENY)

        # A rule that names a specific tool (read_file, ls, bash, …) is constrained
        # to THAT tool; a bare class (network) constrains only the action class so it
        # can cover several tools at once.
        is_tool = action_tool in _TOOL_ACTION
        tools = [action_tool] if is_tool else []
        action_class = _TOOL_ACTION.get(action_tool, action_tool)

        argpat, regex = {}, {}
        if r.get("scope"):
            scope = str(r["scope"]).replace("ws://", "")
            argpat = {"file_path": scope}
        if r.get("match"):
            regex = {"command": _glob_to_regex(str(r["match"]))}

        rules.append(Rule(
            name=f"{agentdef.name}:{i}:{action_tool}:{decision}",
            action=act,
            tools=tools,
            actions=[action_class] if action_class else [],
            argument_patterns=argpat,
            regex=regex,
            priority=base_priority - i,
            message=r.get("message"),
        ))

    default = (perms.get("default") or "deny").lower()
    if default == "deny":
        rules.append(Rule(
            name=f"{agentdef.name}:default-deny",
            action=Action.DENY,
            priority=-1000,
            message="Not permitted by agent definition (default-deny)",
        ))
    return rules


def _glob_to_regex(glob: str) -> str:
    import fnmatch
    return fnmatch.translate(glob)


def register(project, agentdef: AgentDef, definition_md: str | None = None) -> dict:
    """Persist the agent into the registry with its compiled policy YAML-ish blob."""
    import yaml

    from ..store import registry
    policy_repr = yaml.safe_dump(agentdef.permissions) if agentdef.permissions else None
    return registry.register_agent(
        project, agentdef.name,
        description=agentdef.description,
        definition=agentdef.raw_frontmatter,
        model=agentdef.model,
        tools=agentdef.tools,
        definition_md=definition_md,
        policy_yaml=policy_repr,
    )
