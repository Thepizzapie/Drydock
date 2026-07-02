"""Phase 1 runtime tests — full session loop through the real toolbus/kernel/sandbox,
driven by the mock provider (no network, no API key)."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="drydock-rt-")
os.environ["DRYDOCK_HOME"] = _tmp
os.environ["DRYDOCK_NO_EMBED"] = "1"

from drydock.runtime import agentdef as agentdef_mod  # noqa: E402
from drydock.runtime import runner  # noqa: E402
from drydock.runtime.providers.mock import MockProvider, call, turn  # noqa: E402
from drydock.runtime.session import Session  # noqa: E402
from drydock.sandbox.tier0 import Tier0Provider  # noqa: E402
from drydock.store import db, registry, runs as runs_store, service  # noqa: E402
from drydock.store import tickets as tickets_mod  # noqa: E402


AGENT_MD = """\
---
name: editor-bot
description: Edits files in src
model: mock
tools: [read_file, edit_file, write_file, ls, bash, task_done]
max_turns: 20
permissions:
  default: deny
  rules:
    - {action: read_file, scope: "**", decision: allow}
    - {action: write_file, scope: "**", decision: allow}
    - {action: edit_file, scope: "**", decision: allow}
    - {action: ls, decision: allow}
    - {action: bash, match: "echo*", decision: allow}
    - {action: bash, match: "*", decision: ask}
---
You are editor-bot. Make the requested change and call task_done.
"""


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


class RuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(_tmp) / "repo"
        (cls.repo / "src").mkdir(parents=True)
        (cls.repo / "src" / "app.py").write_text("VERSION = '1.0'\n")
        _git(cls.repo, "init", "-q")
        _git(cls.repo, "config", "user.email", "t@t.co")
        _git(cls.repo, "config", "user.name", "t")
        _git(cls.repo, "add", "-A")
        _git(cls.repo, "commit", "-qm", "init")

        cls.project = service.create_project("Runtime Repo", root_path=str(cls.repo))
        cls.agent = agentdef_mod.parse(AGENT_MD)
        agentdef_mod.register("runtime-repo", cls.agent, definition_md=AGENT_MD)

    @classmethod
    def tearDownClass(cls):
        db.close()

    def _session(self, program, ticket=None):
        run = runs_store.create_run("runtime-repo",
                                    agent_id=registry.get_agent("runtime-repo", "editor-bot")["id"])
        prov = Tier0Provider(ticket_key="TEST")
        ws = prov.provision("runtime-repo", run["id"])
        runs_store.set_run_workspace(run["id"], ws.id)
        worker = prov.worker(ws)
        provider = MockProvider("mock").script(program)
        return Session("runtime-repo", run, self.agent, provider, ws, worker,
                       identity="editor-bot@test"), prov, ws, run

    def test_01_read_edit_done(self):
        program = [
            turn("reading", [call("read_file", {"path": "src/app.py"})]),
            turn("editing", [call("edit_file", {"path": "src/app.py",
                 "old_string": "1.0", "new_string": "2.0"})]),
            turn("done", [call("task_done", {"summary": "bumped version to 2.0"})]),
        ]
        session, prov, ws, run = self._session(program)
        out = session.run_loop(instruction="Bump VERSION to 2.0")
        self.assertEqual(out["status"], "done", out)
        self.assertIn("2.0", out["summary"])
        # change landed in the worktree, not the main repo
        edited = (Path(ws.root) / "src" / "app.py").read_text()
        self.assertIn("2.0", edited)
        main = (self.repo / "src" / "app.py").read_text()
        self.assertIn("1.0", main)  # isolation held
        # audit recorded allow decisions
        aud = runs_store.list_audit(run_id=run["id"])
        self.assertTrue(any(a["tool"] == "edit_file" and a["decision"] == "allow" for a in aud))

    def test_02_policy_denies_unpermitted_tool(self):
        # git_diff is not in the agent's allow rules -> default-deny
        program = [
            turn("try git", [call("git_diff", {})]),
            turn("done", [call("task_done", {"summary": "gave up on git"})]),
        ]
        session, prov, ws, run = self._session(program)
        out = session.run_loop()
        self.assertEqual(out["status"], "done")
        aud = runs_store.list_audit(run_id=run["id"])
        self.assertTrue(any(a["tool"] == "git_diff" and a["decision"] == "deny" for a in aud),
                        [(a["tool"], a["decision"]) for a in aud])

    def test_03_ask_pauses_run(self):
        # non-echo, non-destructive command -> agent's catch-all bash rule = ask
        program = [
            turn("build", [call("bash", {"command": "make build"})]),
        ]
        session, prov, ws, run = self._session(program)
        out = session.run_loop()
        self.assertEqual(out["status"], "waiting", out)
        self.assertIn("ask_id", out)
        # the run is parked in 'waiting' and an ask row exists
        self.assertEqual(runs_store.get_run(run["id"])["status"], "waiting")
        pending = runs_store.list_asks(status="pending")
        self.assertTrue(any(a["id"] == out["ask_id"] for a in pending))
        # resolving denies it cleanly
        res = runner.resume_run(run["id"], out["ask_id"], "denied")
        self.assertEqual(res["effective_decision"], "deny")
        self.assertEqual(runs_store.get_ask(out["ask_id"])["status"], "denied")

    def test_04_allowed_bash_runs_in_sandbox(self):
        program = [
            turn("echo", [call("bash", {"command": "echo hello-sandbox"})]),
            turn("done", [call("task_done", {"summary": "ran echo"})]),
        ]
        session, prov, ws, run = self._session(program)
        out = session.run_loop()
        self.assertEqual(out["status"], "done")
        events = runs_store.get_events(run["id"])
        tool_results = [e for e in events if e["type"] == "tool_result"]
        self.assertTrue(any("hello-sandbox" in (e["payload"].get("output") or "")
                            for e in tool_results))

    def test_05_containment_blocks_escape(self):
        # even though policy allows read_file "**", the sandbox worker blocks path escape
        program = [
            turn("escape", [call("read_file", {"path": "../../../../etc/passwd"})]),
            turn("done", [call("task_done", {"summary": "could not escape"})]),
        ]
        session, prov, ws, run = self._session(program)
        out = session.run_loop()
        self.assertEqual(out["status"], "done")
        events = runs_store.get_events(run["id"])
        tr = [e for e in events if e["type"] == "tool_result" and e["payload"].get("tool") == "read_file"]
        self.assertTrue(tr)
        self.assertFalse(tr[0]["payload"]["ok"])
        self.assertIn("escapes workspace", tr[0]["payload"]["error"])

    def test_06_budget_ceiling(self):
        ad = agentdef_mod.parse(AGENT_MD.replace("max_turns: 20", "max_turns: 50"))
        ad.budget = {"tokens": 40}  # tiny ceiling
        run = runs_store.create_run("runtime-repo")
        prov = Tier0Provider(ticket_key="BUD")
        ws = prov.provision("runtime-repo", run["id"])
        worker = prov.worker(ws)
        # each turn costs 30 tokens; ceiling 40 -> stops on the 2nd check
        program = [turn("t1", [call("ls", {"path": "."})], tokens_in=20, tokens_out=10),
                   turn("t2", [call("ls", {"path": "."})], tokens_in=20, tokens_out=10),
                   turn("t3", [call("ls", {"path": "."})], tokens_in=20, tokens_out=10)]
        provider = MockProvider("mock").script(program)
        session = Session("runtime-repo", run, ad, provider, ws, worker)
        out = session.run_loop()
        self.assertEqual(out["status"], "failed")
        self.assertIn("budget", out["summary"])

    def test_07_shell_runner_provisions_only(self):
        out = runner.start_run("runtime-repo", "editor-bot", runner="shell")
        self.assertEqual(out["status"], "workspace_ready")
        self.assertTrue(Path(out["workspace"]).exists())
        self.assertTrue(out["branch"].startswith("drydock/"))

    def test_08_agentdef_compiles_rules(self):
        rules = agentdef_mod.compile_rules(self.agent)
        names = [r.name for r in rules]
        self.assertTrue(any("default-deny" in n for n in names))
        # the ask rule for generic bash exists
        self.assertTrue(any(r.action.value == "ask" for r in rules))


if __name__ == "__main__":
    unittest.main(verbosity=2)
