import json
import tempfile
import unittest
from pathlib import Path

from harness.memory import MemoryStore
from harness.broker import Broker
from harness.ledger import Ledger
from tests.support import OTHER_RUN_ID, make_observation, request_frame, result_frame, recovery_frame
from tests.test_broker import BrokerTestCase, FakeConn
from tests.test_lifecycle import death_auto_frame
from tests.test_modal_broker import modal_frame


class MemoryHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_tools_persist_via_authenticated_mcp_without_game_actions(self):
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
        from websockets.asyncio.client import connect
        from harness.server import Harness
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            harness = Harness(run, ws_port=0, mcp_port=0,
                              memory_dir=Path(directory) / "memory")
            try:
                await harness.start()
                async with connect(f"ws://127.0.0.1:{harness.ws_port}") as game:
                    await game.send(request_frame(1))
                    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + (run / "token").read_text()}) as http:
                        async with Client(streamable_http_client(f"http://127.0.0.1:{harness.mcp_port}/mcp", http_client=http)) as client:
                            names = {tool.name for tool in (await client.list_tools()).tools}
                            self.assertTrue({"memory_status", "memory_write", "memory_search", "memory_read"} <= names)
                            state = (await client.call_tool("get_state", {})).structured_content
                            self.assertEqual(state["memory"]["run_id"], harness.broker.run_id)
                            source = state["memory"]["current_source"]
                            result = await client.call_tool("memory_write", {
                                "expect_seq": 1, "section": "goal", "kind": "plan",
                                "text": "Find Irudad", "sources": [source]})
                            self.assertTrue(result.structured_content["ok"])
                            status = (await client.call_tool("memory_status", {})).structured_content
                            self.assertEqual(status["notes"]["goal"]["text"], "Find Irudad")
                            search = (await client.call_tool("memory_search", {"query": "watervine"})).structured_content
                            self.assertEqual(search["results"][0]["id"], source)
                            read = (await client.call_tool("memory_read", {"source_id": source})).structured_content
                            self.assertEqual(read["seq"], 1)
                            self.assertNotIn("telemetry", json.dumps(read))
                            self.assertEqual(harness.ledger.next_index, 1)
            finally:
                await harness.stop()


class MemoryTests(BrokerTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.memory_dir = Path(self.tmp.name) / "memory"
        self.memory = MemoryStore(self.memory_dir, self.broker)
        self.start()

    async def asyncTearDown(self):
        self.memory.close()
        await super().asyncTearDown()

    def write(self, section="goal", kind="plan", text="Investigate watervine", sources=None):
        status = self.memory.status()
        return self.memory.write(self.broker.seq, section, kind, text,
                                 sources or [status["current_source"]])

    async def test_notes_and_sources_survive_new_harness_run_but_need_revalidation(self):
        self.assertTrue(self.write()["ok"])
        self.write("inventory", "fact", "Carrying a copper wire")
        self.memory.close()
        ledger2 = Ledger.create(Path(self.tmp.name) / "second.jsonl")
        broker2 = Broker(ledger2)
        conn2 = FakeConn()
        broker2.attach(conn2)
        broker2.handle_frame(conn2, request_frame(1, run_id=OTHER_RUN_ID, turn=0))
        other = MemoryStore(self.memory_dir, broker2)
        try:
            status = other.status()
            self.assertEqual(status["notes"]["goal"]["text"], "Investigate watervine")
            self.assertEqual(status["notes"]["inventory"]["validity"], "needs_revalidation")
            self.assertFalse(status["notes"]["goal"]["same_timeline"])
            self.assertEqual(other.search("watervine")["results"][0]["run_id"], self.broker.run_id)
        finally:
            other.close()
            ledger2.close()

    async def test_recovery_preserves_lessons_and_invalidates_old_progress(self):
        self.write("progress", "fact", "Found the corpse")
        self.write("lesson", "lesson", "Retreat before HP gets low")
        self.broker.handle_frame(self.conn, recovery_frame(1))
        suspended = self.memory.status()
        self.assertIsNone(suspended["current_source"])
        self.assertEqual(suspended["notes"]["progress"]["validity"], "needs_revalidation")
        self.broker.handle_frame(self.conn, request_frame(2, turn=0))
        resumed = self.memory.status()
        self.assertEqual(resumed["notes"]["lesson"]["kind"], "lesson")
        self.assertFalse(resumed["notes"]["lesson"]["same_timeline"])
        self.assertTrue(self.write("progress", "fact", "Quest still active")["ok"])
        self.assertEqual(self.memory.status()["notes"]["progress"]["validity"], "player_report")

    async def test_search_returns_provenance_without_hidden_telemetry(self):
        results = self.memory.search("watervine")["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["seq"], 1)
        self.assertEqual(results[0]["turn"], 1)
        self.assertEqual(results[0]["kind"], "request")
        source = self.memory.read(results[0]["id"])
        self.assertEqual(source["record"]["observation"]["vitals"]["hp"], 14)
        self.assertNotIn("telemetry", json.dumps(source))
        self.assertNotIn("game_queue", json.dumps(source))
        self.assertNotIn("map", source["record"]["observation"])
        self.assertEqual(self.memory.search("watervine")["results"], results)

    async def test_stale_or_invented_citations_cannot_overwrite_notes(self):
        self.write()
        for args in ((0, "goal", "plan", "bad", []),
                     (1, "goal", "fact", "bad", ["f" * 64]),
                     (1, "goal", "fact", "bad", []),
                     (1, "goal", "fact", " " , [])):
            self.assertFalse(self.memory.write(*args)["ok"])
        self.assertEqual(self.memory.status()["notes"]["goal"]["text"], "Investigate watervine")
        self.assertEqual(self.kinds(), [("request", 1)])

    async def test_old_evidence_cannot_be_relabelled_current_after_recovery(self):
        source = self.memory.status()["current_source"]
        self.broker.handle_frame(self.conn, recovery_frame(1))
        self.broker.handle_frame(self.conn, request_frame(2, turn=0))
        result = self.memory.write(2, "inventory", "fact", "Still have copper wire", [source])
        self.assertFalse(result["ok"])
        self.assertTrue(self.memory.write(2, "lesson", "lesson", "Old failure", [source])["ok"])

    async def test_episode_due_after_ten_decisions_and_summary_resets_it(self):
        for seq in range(1, 11):
            await self.broker.act(seq, "wait")
            self.broker.handle_frame(self.conn, result_frame(seq, action="wait", turn=seq+1))
            self.broker.handle_frame(self.conn, request_frame(seq+1, turn=seq+1))
        self.assertTrue(self.memory.status()["episode_due"])
        self.assertTrue(self.write("summary", "summary", "Explored ten turns")["ok"])
        self.assertFalse(self.memory.status()["episode_due"])

    async def test_second_memory_writer_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "already in use"):
            MemoryStore(self.memory_dir, self.broker)

    async def test_query_log_records_cutoff_results_and_latency(self):
        response = self.memory.search("watervine")
        import sqlite3
        with sqlite3.connect(self.memory_dir / "memory.sqlite3") as db:
            row = db.execute("SELECT request, response, duration_ms FROM calls WHERE tool='search'").fetchone()
        self.assertEqual(json.loads(row[0])["query"], "watervine")
        self.assertEqual(json.loads(row[1])["results"][0]["id"], response["results"][0]["id"])
        self.assertGreaterEqual(row[2], 0)

    async def test_truncated_or_modified_ledger_is_not_silently_indexed(self):
        self.memory.status()
        with self.ledger_path.open("ab") as handle:
            handle.write(b'{"bad":')
        result = self.memory.search("watervine")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "memory_error")

    async def test_inactive_game_cannot_create_current_facts(self):
        self.memory.status()
        self.broker.detach(self.conn)
        self.assertIsNone(self.memory.status()["current_source"])
        self.assertFalse(self.write()["ok"])

    async def test_fts_punctuation_and_empty_query_are_bounded(self):
        self.assertFalse(self.memory.search(" ")["ok"])
        self.assertTrue(self.memory.search('"watervine" OR * : -')["ok"])
        self.assertFalse(self.memory.search("watervine", limit=1000)["ok"])

    async def test_death_evidence_is_directly_available_after_checkpoint_restore(self):
        self.broker.handle_frame(self.conn, death_auto_frame())
        self.broker.handle_frame(self.conn, death_auto_frame(token="death-2"))
        self.broker.handle_frame(self.conn, recovery_frame(1))
        self.broker.handle_frame(self.conn, request_frame(2, turn=0))
        status = self.memory.status()
        self.assertIn("lifecycle", status)
        life = status["lifecycle"]
        self.assertEqual(life["scope"], "campaign")
        self.assertEqual(life["death_count"], 1)
        self.assertEqual(life["recovery_count"], 1)
        self.assertEqual(life["lost_turns"], 20)
        death = life["recent_deaths"][0]
        self.assertEqual(death["text"], "You died.")
        self.assertTrue(self.memory.read(death["source_id"])["ok"])
        self.memory.close()
        self.memory = MemoryStore(self.memory_dir, self.broker)
        self.assertEqual(self.memory.status()["lifecycle"], life)

    async def test_save_reload_is_not_inferred_to_be_a_death(self):
        self.broker.handle_frame(self.conn, recovery_frame(1, reason="save_reload"))
        status = self.memory.status()
        self.assertIn("lifecycle", status)
        self.assertEqual(status["lifecycle"]["death_count"], 0)
        self.assertEqual(status["lifecycle"]["recovery_count"], 1)

    async def test_search_deduplicates_result_and_next_request_but_keeps_outcome(self):
        await self.broker.act(1, "wait", rationale="The watervine is safe")
        self.broker.handle_frame(self.conn, result_frame(1, action="wait", turn=2))
        self.broker.handle_frame(self.conn, request_frame(2, turn=2))
        hits = self.memory.search("watervine", limit=10)["results"]
        self.assertEqual(len(hits), 2)
        self.assertEqual({h["kind"] for h in hits}, {"request", "result"})
        self.assertEqual({h["turn"] for h in hits}, {1, 2})

    async def test_search_zone_and_timeline_filters_do_not_return_other_floor(self):
        self.memory.status()
        self.broker.handle_frame(self.conn, recovery_frame(1))
        obs = make_observation(turn=0)
        obs["vitals"]["zone"] = "JoppaWorld.11.20.1.1.12"
        self.broker.handle_frame(self.conn, request_frame(2, observation=obs))
        hits = self.memory.search("watervine", zone=obs["vitals"]["zone"], current_timeline=True)
        self.assertTrue(hits["ok"])
        self.assertEqual([(h["seq"], h["same_timeline"]) for h in hits["results"]], [(2, True)])
        self.assertEqual(self.memory.search("watervine", zone="unknown")["results"], [])

    async def test_search_excerpt_keeps_threat_and_location_when_inventory_is_long(self):
        obs = make_observation(turn=2)
        obs["kit"] = [{"id": f"i{n}", "name": "copper " + "x" * 180, "slot": None} for n in range(1, 31)]
        await self.broker.act(1, "wait")
        self.broker.handle_frame(self.conn, result_frame(1, action="wait", observation=obs))
        self.broker.handle_frame(self.conn, request_frame(2, observation=obs))
        hit = next(h for h in self.memory.search("copper", limit=10)["results"] if h["turn"] == 2)
        excerpt = json.loads(hit["excerpt"])
        self.assertEqual(excerpt["observation"]["vitals"]["turn"], 2)
        self.assertEqual(excerpt["observation"]["threats"][0]["name"], "snapjaw scavenger")
        self.assertLessEqual(len(hit["excerpt"]), 3000)

    async def test_checkpoint_saves_short_plan_and_conditions_atomically(self):
        self.write("places", "hypothesis", "Stairs at 12,3")
        source = self.memory.status()["current_source"]
        result = self.memory.checkpoint(1, "Retreated", "Keep retreating", "Strong enemy nearby",
                                        "Reconsider only after new wound evidence", [source])
        self.assertTrue(result["ok"])
        status = self.memory.status()
        self.assertEqual(status["notes"]["places"]["text"], "Stairs at 12,3")
        self.assertEqual(status["focus"]["plan"]["text"], "Keep retreating")
        self.assertEqual(status["focus"]["reconsider_when"]["text"], "Reconsider only after new wound evidence")
        self.assertEqual(status["decisions_since_summary"], 0)
        before = dict(status["notes"])
        result = self.memory.checkpoint(1, "bad", "replace", "x" * 1201, "bad", [source])
        self.assertFalse(result["ok"])
        self.assertEqual(self.memory.status()["notes"], before)
        self.broker.handle_frame(self.conn, recovery_frame(1))
        self.assertEqual(self.memory.status()["focus"]["plan"]["validity"], "needs_revalidation")

    async def test_search_excerpt_includes_matching_quest_and_ground_evidence(self):
        obs = make_observation(turn=2)
        obs["goals"] = {"text": "Prior quest details. " * 80 + "Find the chromeling.", "truncated": False}
        obs["ground"] = [{"id": "p1", "name": "electrified longsword", "x": 40, "y": 12}]
        await self.broker.act(1, "wait")
        self.broker.handle_frame(self.conn, result_frame(1, action="wait", observation=obs))
        self.broker.handle_frame(self.conn, request_frame(2, observation=obs))
        for query, field in (("chromeling", "goals"), ("longsword", "ground")):
            with self.subTest(query=query):
                hit = self.memory.search(query)["results"][0]
                excerpt = json.loads(hit["excerpt"])
                self.assertIn(query, json.dumps(excerpt["observation"].get(field, {})))
                self.assertLessEqual(len(hit["excerpt"]), 3000)
                self.assertIn("vitals", excerpt["observation"])

    async def test_pending_modal_cannot_commit_memory_as_current_observation(self):
        source = self.memory.status()["current_source"]
        await self.broker.act(1, "wait")
        self.broker.handle_frame(self.conn, modal_frame())
        self.assertTrue(self.broker.get_state()["ok"])
        self.assertIsNone(self.memory.status()["current_source"])
        self.assertFalse(self.memory.write(1, "progress", "fact", "Done", [source])["ok"])
        self.assertFalse(self.memory.checkpoint(1, "Done", "Next", "None", "New evidence", [source])["ok"])
        self.assertEqual(self.memory.status()["notes"], {})

    async def test_memory_write_and_audit_commit_together(self):
        source = self.memory.status()["current_source"]
        for tool in ("write", "checkpoint"):
            with self.subTest(tool=tool):
                self.memory.db.execute("""CREATE TEMP TRIGGER reject_call BEFORE INSERT ON calls
                    BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END""")
                try:
                    if tool == "write":
                        result = self.memory.write(1, "progress", "fact", "Done", [source])
                    else:
                        result = self.memory.checkpoint(1, "Done", "Next", "None", "New evidence", [source])
                    self.assertFalse(result["ok"])
                    self.assertEqual(self.memory.db.execute("SELECT count(*) FROM notes").fetchone()[0], 0)
                finally:
                    self.memory.db.execute("DROP TRIGGER reject_call")
