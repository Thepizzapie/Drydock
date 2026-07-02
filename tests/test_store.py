"""Phase 0 store tests — full PM-plane roundtrip on a temp database.

Run: python -m unittest discover -s tests -v   (no third-party deps needed)
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="drydock-test-")
os.environ["DRYDOCK_HOME"] = _tmp
os.environ["DRYDOCK_NO_EMBED"] = "1"  # tests never touch the network

from drydock.store import allocator, db, fts, planning, registry, service  # noqa: E402
from drydock.store import tickets as tickets_mod  # noqa: E402


class StoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(_tmp) / "fakerepo"
        (cls.repo / "src").mkdir(parents=True)
        (cls.repo / "src" / "orders.py").write_text("def create_order():\n    pass\n")
        cls.project = service.create_project(
            "Shipping Platform", root_path=str(cls.repo))

    @classmethod
    def tearDownClass(cls):
        db.close()

    def test_01_project(self):
        p = self.project
        self.assertEqual(p["slug"], "shipping-platform")
        self.assertEqual(p["ticket_prefix"], "SP")
        self.assertTrue(service.get_project("shipping-platform"))
        self.assertEqual(len(service.list_repos("shipping-platform")), 1)

    def test_02_memories_and_search(self):
        service.add_memory("shipping-platform",
                           "We chose SQLite over Postgres to kill install friction.",
                           title="Storage choice", kind="semantic",
                           tags=["storage"], importance=0.9)
        service.add_memory("shipping-platform",
                           "Payment failures should show actionable error messages.",
                           title="Payment errors UX", importance=0.6)
        pinned = service.add_memory("shipping-platform",
                                    "Always run tests before merging.",
                                    title="Merge rule", pinned=True, importance=0.8)
        self.assertTrue(pinned["pinned"])

        hits = service.search_context("shipping-platform", "sqlite postgres install", k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["title"], "Storage choice")
        # recall touched last_accessed
        row = db.one("SELECT last_accessed FROM memories WHERE id=?", (hits[0]["id"],))
        self.assertIsNotNone(row["last_accessed"])

    def test_03_decisions_supersede(self):
        d1 = service.log_decision("shipping-platform", "Use Postgres",
                                  rationale="familiar")
        d2 = service.log_decision("shipping-platform", "Use SQLite",
                                  rationale="install friction", supersedes=d1["id"])
        active = service.get_decisions("shipping-platform", active_only=True)
        titles = [d["title"] for d in active]
        self.assertIn("Use SQLite", titles)
        self.assertNotIn("Use Postgres", titles)
        self.assertEqual(d2["status"], "active")

    def test_04_handoff_lifecycle(self):
        service.create_handoff("shipping-platform", summary="first")
        h2 = service.create_handoff("shipping-platform", summary="second",
                                    next_steps=["port FTS queries"])
        active = service.get_handoff("shipping-platform")
        self.assertEqual(active["id"], h2["id"])
        self.assertEqual(active["next_steps"], ["port FTS queries"])
        consumed = db.q("SELECT * FROM handoffs WHERE status='consumed'")
        self.assertEqual(len(consumed), 1)

    def test_05_tickets_keys(self):
        t1 = tickets_mod.create_ticket("shipping-platform", "First ticket")
        t2 = tickets_mod.create_ticket("shipping-platform", "Second ticket", priority=1)
        self.assertEqual(t1["key"], "SP-1")
        self.assertEqual(t2["key"], "SP-2")
        self.assertEqual(tickets_mod.get_ticket("shipping-platform", "SP-2")["id"], t2["id"])
        upd = tickets_mod.update_ticket("shipping-platform", "SP-1", status="ready")
        self.assertEqual(upd["status"], "ready")

    def test_06_plan_to_brief(self):
        plan = {
            "summary": "Add request validation for create order",
            "steps": [
                {"title": "Validate payload shape", "files": ["src/orders.py"],
                 "suggested_role": "backend"},
                {"title": "Add tests", "files": ["tests/test_orders.py"]},
            ],
            "risks": ["breaking existing clients"],
        }
        out = planning.create_ticket_from_plan("shipping-platform", plan, priority=1)
        self.assertEqual(len(out["tasks"]), 2)
        self.assertEqual(out["tasks"][0]["files"], ["src/orders.py"])

        readiness = planning.ticket_readiness("shipping-platform", out["ticket"]["id"])
        self.assertTrue(readiness["ready"], readiness)

        brief = planning.task_brief("shipping-platform", out["tasks"][0]["task_id"])
        self.assertEqual(brief["ticket"]["id"], out["ticket"]["id"])
        self.assertIn("Plan", brief["plan"]["title"])
        self.assertEqual(brief["files"][0]["path"], "src/orders.py")
        self.assertTrue(brief["files"][0]["context"]["found"])
        self.assertIn("def create_order", brief["files"][0]["context"]["content"])
        self.assertEqual(len(brief["siblings"]), 1)

        rendered = planning.render_brief(brief)
        self.assertIn("# PLAN", rendered)
        self.assertIn("src/orders.py", rendered)

    def test_07_allocator_budget(self):
        packet = allocator.assemble("shipping-platform", token_budget=200)
        self.assertLessEqual(
            packet["total_tokens"] - sum(
                i["tokens"] for i in packet["items"]
                if i["type"] == "memory" and i.get("id") and db.one(
                    "SELECT pinned FROM memories WHERE id=?", (i["id"],))["pinned"]),
            200)
        # pinned memory always present
        titles = [i["title"] for i in packet["items"]]
        self.assertIn("Merge rule", titles)
        rendered = allocator.render(packet)
        self.assertIn("# Context", rendered)

    def test_08_resume(self):
        out = service.resume("shipping-platform", token_budget=500)
        self.assertEqual(out["project"]["slug"], "shipping-platform")
        self.assertIsNotNone(out["handoff"])
        self.assertTrue(out["active_decisions"])
        self.assertIn("context", out)

    def test_09_registry(self):
        a1 = registry.register_agent("shipping-platform", "refactor-bot",
                                     description="v1", tools=["read_file"])
        a2 = registry.register_agent("shipping-platform", "refactor-bot",
                                     description="v2", tools=["read_file", "edit_file"])
        self.assertEqual(a1["id"], a2["id"])
        self.assertEqual(a2["version"], 2)
        self.assertEqual(a2["tools"], ["read_file", "edit_file"])
        got = registry.get_agent("shipping-platform", "refactor-bot")
        self.assertEqual(got["description"], "v2")

    def test_10_fts_tickets(self):
        hits = fts.search_tickets("shipping-platform", "request validation")
        self.assertTrue(any("validation" in (h["title"] or "").lower() for h in hits))

    def test_11_attempts(self):
        service.log_attempt("shipping-platform", "Tried tsvector in SQLite",
                            "failed", why="not a thing — use FTS5")
        atts = service.get_attempts("shipping-platform")
        self.assertTrue(atts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
