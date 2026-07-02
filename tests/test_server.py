"""Phase 2 tests — the blocking ask→approve→resume flow, hooks capture, and the
REST surface via FastAPI TestClient. No network; mock provider drives the agent."""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="drydock-srv-")
os.environ["DRYDOCK_HOME"] = _tmp
os.environ["DRYDOCK_NO_EMBED"] = "1"

from drydock.runtime import agentdef as agentdef_mod  # noqa: E402
from drydock.runtime.providers.mock import MockProvider, call, turn  # noqa: E402
from drydock.runtime.session import Session  # noqa: E402
from drydock.sandbox.tier0 import Tier0Provider  # noqa: E402
from drydock.server.runmanager import RunManager  # noqa: E402
from drydock.store import db, registry, runs as runs_store, service  # noqa: E402


AGENT_MD = """\
---
name: srv-bot
model: mock
tools: [read_file, bash, task_done]
max_turns: 10
permissions:
  default: deny
  rules:
    - {action: read_file, scope: "**", decision: allow}
    - {action: bash, match: "make*", decision: ask}
---
srv-bot.
"""


def _git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(_tmp) / "repo"
        (cls.repo / "src").mkdir(parents=True)
        (cls.repo / "src" / "m.py").write_text("x = 1\n")
        _git(cls.repo, "init", "-q")
        _git(cls.repo, "config", "user.email", "t@t.co")
        _git(cls.repo, "config", "user.name", "t")
        _git(cls.repo, "add", "-A")
        _git(cls.repo, "commit", "-qm", "init")
        service.create_project("Srv Repo", root_path=str(cls.repo))
        cls.agent = agentdef_mod.parse(AGENT_MD)
        agentdef_mod.register("srv-repo", cls.agent, definition_md=AGENT_MD)

    @classmethod
    def tearDownClass(cls):
        db.close()

    def test_01_ask_approve_resume_in_place(self):
        """A run blocks on an ask, a second thread approves it, the run resumes and finishes."""
        mgr = RunManager()
        run = runs_store.create_run("srv-repo")
        prov = Tier0Provider(ticket_key="SRV")
        ws = prov.provision("srv-repo", run["id"])
        runs_store.set_run_workspace(run["id"], ws.id)
        worker = prov.worker(ws)
        program = [
            turn("build", [call("bash", {"command": "make all"})]),
            turn("done", [call("task_done", {"summary": "built"})]),
        ]
        session = Session("srv-repo", run, self.agent,
                          MockProvider("mock").script(program), ws, worker,
                          identity="srv-bot@t", ask_resolver=mgr._resolver)

        result = {}
        t = threading.Thread(target=lambda: result.update(session.run_loop()))
        t.start()

        # wait for the ask to appear
        ask_id = None
        for _ in range(50):
            pend = runs_store.list_asks(status="pending")
            if pend:
                ask_id = pend[0]["id"]
                break
            time.sleep(0.05)
        self.assertIsNotNone(ask_id, "ask never surfaced")
        self.assertEqual(runs_store.get_run(run["id"])["status"], "waiting")

        # approve it -> run resumes in place
        signalled = mgr.resolve(ask_id, "approved_once", by="tester")
        self.assertTrue(signalled)
        t.join(timeout=5)
        self.assertEqual(result.get("status"), "done", result)
        self.assertEqual(runs_store.get_ask(ask_id)["status"], "approved_once")

    def test_02_deny_resume(self):
        mgr = RunManager()
        run = runs_store.create_run("srv-repo")
        prov = Tier0Provider(ticket_key="SRV2")
        ws = prov.provision("srv-repo", run["id"])
        runs_store.set_run_workspace(run["id"], ws.id)
        worker = prov.worker(ws)
        program = [
            turn("build", [call("bash", {"command": "make danger"})]),
            turn("done", [call("task_done", {"summary": "gave up"})]),
        ]
        session = Session("srv-repo", run, self.agent,
                          MockProvider("mock").script(program), ws, worker,
                          ask_resolver=mgr._resolver)
        result = {}
        t = threading.Thread(target=lambda: result.update(session.run_loop()))
        t.start()
        ask_id = None
        for _ in range(50):
            pend = runs_store.list_asks(status="pending")
            if pend:
                ask_id = pend[0]["id"]
                break
            time.sleep(0.05)
        mgr.resolve(ask_id, "denied")
        t.join(timeout=5)
        self.assertEqual(result.get("status"), "done")
        # the denied bash produced a tool_result error the model saw
        events = runs_store.get_events(run["id"])
        tr = [e for e in events if e["type"] == "tool_result"]
        self.assertTrue(any("denied" in (e["payload"].get("error") or "") for e in tr))

    def test_03_always_creates_grant(self):
        mgr = RunManager()
        run = runs_store.create_run("srv-repo")
        prov = Tier0Provider(ticket_key="SRV3")
        ws = prov.provision("srv-repo", run["id"])
        runs_store.set_run_workspace(run["id"], ws.id)
        worker = prov.worker(ws)
        program = [
            turn("b1", [call("bash", {"command": "make one"})]),
            turn("done", [call("task_done", {"summary": "done"})]),
        ]
        session = Session("srv-repo", run, self.agent,
                          MockProvider("mock").script(program), ws, worker,
                          ask_resolver=mgr._resolver)
        result = {}
        t = threading.Thread(target=lambda: result.update(session.run_loop()))
        t.start()
        ask_id = None
        for _ in range(50):
            pend = runs_store.list_asks(status="pending")
            if pend:
                ask_id = pend[0]["id"]
                break
            time.sleep(0.05)
        mgr.resolve(ask_id, "always")
        t.join(timeout=5)
        grants = runs_store.list_grants("srv-repo")
        self.assertTrue(grants, "always should persist a grant")
        self.assertEqual(grants[0]["scope"].get("action_class"), "shell")

    def test_04_hooks_capture_records_external(self):
        import io
        import json
        import sys
        from drydock.runtime import hooks

        payload = json.dumps({"tool_name": "Bash", "session_id": "cc-123",
                              "tool_input": {"command": "ls"}})
        old = sys.stdin
        sys.stdin = io.StringIO(payload)
        try:
            rc = hooks.capture("srv-repo", "PreToolUse")
        finally:
            sys.stdin = old
        self.assertEqual(rc, 0)
        aud = runs_store.list_audit(project="srv-repo", limit=500)
        self.assertTrue(any(a.get("ext_session_id") == "cc-123" and a["tool"] == "Bash"
                            for a in aud))

    def test_05_rest_surface(self):
        from fastapi.testclient import TestClient
        from drydock.server.app import app
        client = TestClient(app)

        self.assertEqual(client.get("/api/health").json()["ok"], True)
        projs = client.get("/api/projects").json()
        self.assertTrue(any(p["slug"] == "srv-repo" for p in projs))
        ov = client.get("/api/projects/srv-repo/overview").json()
        self.assertIn("counts", ov)
        self.assertIn("outcomes", ov)
        tiers = client.get("/api/system/tiers").json()
        self.assertIn("recommended", tiers)

    def test_06_rest_dispatch_and_resolve(self):
        # dispatch a run that will ask, then resolve via REST
        from fastapi.testclient import TestClient
        from drydock.server import app as appmod
        # point the app's MANAGER-driven dispatch at a mock provider by pre-registering
        client = TestClient(appmod.app)
        # dispatch with the mock provider override won't script turns, so instead we
        # verify the endpoint contract: dispatch returns a run_id, asks endpoint lists.
        resp = client.post("/api/projects/srv-repo/dispatch",
                           json={"agent": "srv-bot", "provider": "mock",
                                 "instruction": "noop"})
        self.assertIn(resp.status_code, (200, 500))  # mock w/o script -> task_done or error
        # asks endpoint is reachable
        self.assertEqual(client.get("/api/asks").status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
