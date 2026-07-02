"""Drydock CLI.

Phase 0 commands: init, doctor, mcp, version. (up/run/agent/tier land in later phases.)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, config

_DEFAULT_POLICY = """\
# Drydock project policy (aegis-shaped). Applied to every agent in this project.
# Layering: aegis built-ins (non-escapable) > this file > agent frontmatter > grants.
default_action: allow
on_error: allow

egress:
  default: deny
  allow: []

rules:
  - name: block-secret-files
    priority: 150
    action: deny
    actions: [read, edit, write]
    argument_patterns:
      file_path: "*.env*"
    message: "Reading/writing .env files is blocked"
"""


def _git_root(start: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return Path(out.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def cmd_init(args) -> int:
    from .store import service

    cwd = Path.cwd()
    root = _git_root(cwd) or cwd
    name = args.name or root.name

    config.ensure_home()
    existing = None
    for p in service.list_projects():
        if p.get("root_path") and Path(p["root_path"]).resolve() == root.resolve():
            existing = p
            break

    if existing:
        project = existing
        print(f"project already registered: {project['slug']} ({project['root_path']})")
    else:
        project = service.create_project(name, root_path=str(root))
        print(f"registered project: {project['slug']}  prefix={project['ticket_prefix']}  root={root}")

    dd = config.project_dir(root)
    dd.mkdir(exist_ok=True)
    (dd / "agents").mkdir(exist_ok=True)
    policy = dd / "policy.yaml"
    if not policy.exists():
        policy.write_text(_DEFAULT_POLICY, encoding="utf-8")
        print(f"wrote {policy}")
    settings = dd / "settings.json"
    if not settings.exists():
        settings.write_text(json.dumps({"project": project["slug"]}, indent=2), encoding="utf-8")
        print(f"wrote {settings}")

    print(f"db: {config.db_path()}")
    return 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    mark = "ok " if ok else "-- "
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def cmd_doctor(args) -> int:
    print(f"drydock {__version__}")
    print(f"home: {config.home()}")

    # db
    try:
        from .store import db
        db.connect()
        _check("sqlite", True, f"{config.db_path()}")
    except Exception as exc:
        _check("sqlite", False, str(exc))

    # git
    _check("git", shutil.which("git") is not None)

    # wsl (tier 1)
    wsl = shutil.which("wsl")
    wsl_ok = False
    if wsl:
        try:
            out = subprocess.run([wsl, "--status"], capture_output=True, timeout=10)
            wsl_ok = out.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    _check("wsl2 (tier 1)", wsl_ok, "run `wsl --install` to enable the hard sandbox" if not wsl_ok else "")

    # docker (tier 2)
    docker_ok = False
    if shutil.which("docker"):
        try:
            out = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                 capture_output=True, timeout=10)
            docker_ok = out.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    _check("docker (tier 2)", docker_ok)

    # embeddings
    try:
        from .store import embeddings
        b = embeddings.backend()
        _check("embeddings", b != "none", b if b != "none" else "FTS-only recall (fine)")
    except Exception as exc:
        _check("embeddings", False, str(exc))

    # vectors
    try:
        import chromadb  # noqa: F401
        _check("vectors (chromadb)", True)
    except ImportError:
        _check("vectors (chromadb)", False, "pip install drydock-ai[vectors]")

    tier = 1 if wsl_ok else (2 if docker_ok else 0)
    print(f"\nrecommended isolation tier: {tier}")
    return 0


def cmd_mcp(args) -> int:
    from .mcp.server import run
    run()
    return 0


def _project_for_cwd() -> str | None:
    """Resolve the project registered for the current repo (from .drydock/settings.json)."""
    root = _git_root(Path.cwd()) or Path.cwd()
    settings = config.project_dir(root) / "settings.json"
    if settings.exists():
        try:
            return json.loads(settings.read_text(encoding="utf-8")).get("project")
        except (json.JSONDecodeError, OSError):
            pass
    from .store import service
    for p in service.list_projects():
        if p.get("root_path") and Path(p["root_path"]).resolve() == root.resolve():
            return p["slug"]
    return None


def cmd_run(args) -> int:
    from .runtime import runner

    project = args.project or _project_for_cwd()
    if not project:
        print("no project — run `drydock init` here first, or pass --project")
        return 1
    if args.runner == "claude":
        from .runtime.runners_external import run_claude
        out = run_claude(project, ticket=args.ticket, tier=args.tier,
                         instruction=args.instruction)
    else:
        out = runner.start_run(
            project, args.agent, ticket=args.ticket, tier=args.tier,
            provider_override=args.provider, instruction=args.instruction,
            runner=args.runner)
    print(json.dumps(out, indent=2))
    return 0 if out.get("status") in ("done", "workspace_ready", "waiting") else 2


def cmd_agent(args) -> int:
    from .runtime import agentdef as agentdef_mod
    from .store import registry

    project = args.project or _project_for_cwd()
    if args.action == "list":
        for a in registry.list_agents(project):
            print(f"  {a['name']:20} v{a.get('version', 1)}  {a.get('description', '')}")
        return 0
    if args.action == "add":
        ad = agentdef_mod.load_file(args.path)
        md = Path(args.path).read_text(encoding="utf-8")
        row = agentdef_mod.register(project, ad, definition_md=md)
        print(f"registered agent {row['name']} v{row.get('version', 1)} "
              f"({len(ad.tools)} tools, {len(ad.permissions.get('rules', []))} policy rules)")
        return 0
    if args.action == "show":
        a = registry.get_agent(project, args.path)
        print(json.dumps(a, indent=2) if a else "not found")
        return 0 if a else 1
    return 1


def cmd_up(args) -> int:
    import webbrowser
    from .server.app import serve
    url = f"http://{args.host}:{args.port}"
    print(f"drydock server: {url}")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    serve(host=args.host, port=args.port)
    return 0


def cmd_hooks(args) -> int:
    from .runtime.hooks import install
    project = args.project or _project_for_cwd()
    root = _git_root(Path.cwd()) or Path.cwd()
    if not project:
        print("no project — run `drydock init` here first")
        return 1
    out = install(str(root), project)
    print(f"installed capture hooks in {out['settings']}")
    print(f"events: {', '.join(out['events'])}")
    print("external Claude Code sessions in this repo now report into Drydock.")
    return 0


def cmd_hookcapture(args) -> int:
    from .runtime.hooks import capture
    return capture(args.project, args.event)


def cmd_workspace(args) -> int:
    from .runtime import runner

    project = args.project or _project_for_cwd()
    if not project:
        print("no project — run `drydock init` here first")
        return 1
    out = runner.start_run(project, args.agent or "shell-user", ticket=args.ticket,
                           tier=args.tier, runner="shell")
    print(f"workspace ready: {out.get('workspace')}")
    if out.get("branch"):
        print(f"branch: {out['branch']}")
    print("launch any agent in that directory; review with `git diff` then merge the branch.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="drydock",
        description="Agents work in drydock, not on your ship.")
    parser.add_argument("--version", action="version", version=f"drydock {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="register this repo as a Drydock project")
    p_init.add_argument("--name", help="project name (default: repo folder name)")
    p_init.set_defaults(fn=cmd_init)

    p_doc = sub.add_parser("doctor", help="check environment and isolation tiers")
    p_doc.set_defaults(fn=cmd_doctor)

    p_mcp = sub.add_parser("mcp", help="run the MCP server (stdio)")
    p_mcp.set_defaults(fn=cmd_mcp)

    p_run = sub.add_parser("run", help="run an agent on a ticket in a sandbox")
    p_run.add_argument("agent", help="agent name or path to a .md definition")
    p_run.add_argument("--project")
    p_run.add_argument("--ticket", help="ticket key (e.g. TCK-12)")
    p_run.add_argument("--tier", type=int, default=0, choices=[0, 1, 2])
    p_run.add_argument("--provider", help="override provider (mock|anthropic|openai)")
    p_run.add_argument("--runner", default="native", choices=["native", "shell", "claude"])
    p_run.add_argument("--instruction", help="one-off instruction instead of a ticket brief")
    p_run.set_defaults(fn=cmd_run)

    p_agent = sub.add_parser("agent", help="manage agent definitions")
    p_agent.add_argument("action", choices=["list", "add", "show"])
    p_agent.add_argument("path", nargs="?", help=".md path (add) or name (show)")
    p_agent.add_argument("--project")
    p_agent.set_defaults(fn=cmd_agent)

    p_ws = sub.add_parser("workspace", help="provision a sandbox workspace for manual/external agent use")
    p_ws.add_argument("--project")
    p_ws.add_argument("--ticket")
    p_ws.add_argument("--agent")
    p_ws.add_argument("--tier", type=int, default=0, choices=[0, 1, 2])
    p_ws.set_defaults(fn=cmd_workspace)

    p_up = sub.add_parser("up", help="start the Drydock server + dashboard")
    p_up.add_argument("--host", default="127.0.0.1")
    p_up.add_argument("--port", type=int, default=4400)
    p_up.add_argument("--no-browser", action="store_true")
    p_up.set_defaults(fn=cmd_up)

    p_hooks = sub.add_parser("hooks", help="install capture hooks so external agents report into Drydock")
    p_hooks.add_argument("action", choices=["install"])
    p_hooks.add_argument("--project")
    p_hooks.set_defaults(fn=cmd_hooks)

    p_hc = sub.add_parser("hookcapture", help="(internal) receive an external agent hook payload")
    p_hc.add_argument("event")
    p_hc.add_argument("--project", required=True)
    p_hc.set_defaults(fn=cmd_hookcapture)

    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        parser.print_help()
        return 1
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
