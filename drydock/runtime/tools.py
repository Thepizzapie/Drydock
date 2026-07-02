"""Tool schemas exposed to the model (Anthropic tool-use format).

Execution lives in the sandbox worker; this module only declares the contract.
`task_done` is the terminal tool — the model calls it to end the run with a summary.
"""
from __future__ import annotations

TOOL_SCHEMAS = {
    "read_file": {
        "description": "Read a file inside the workspace. Path is relative to the workspace root.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    "write_file": {
        "description": "Create or overwrite a file inside the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    "edit_file": {
        "description": "Replace a unique substring in a file. old_string must appear exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    "ls": {
        "description": "List a directory in the workspace.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
    "glob": {
        "description": "Find files by glob pattern (e.g. src/**/*.py) inside the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    },
    "grep": {
        "description": "Search file contents by regex inside the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
            "required": ["pattern"],
        },
    },
    "bash": {
        "description": "Run a shell command in the workspace (scrubbed env, timeout). "
                       "Subject to policy — may be denied or held for approval.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    "git_status": {
        "description": "Show `git status --porcelain` for the workspace.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "git_diff": {
        "description": "Show the working-tree diff for the workspace.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "task_done": {
        "description": "Call this when the task is complete. Provide a short summary of what changed.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
}


def schemas_for(tool_names: list[str]) -> list[dict]:
    """Anthropic tools[] payload for the agent's declared tools (+ task_done always)."""
    names = list(dict.fromkeys(list(tool_names) + ["task_done"]))
    out = []
    for n in names:
        s = TOOL_SCHEMAS.get(n)
        if s:
            out.append({"name": n, "description": s["description"],
                        "input_schema": s["input_schema"]})
    return out
