import json
from copy import deepcopy
from unittest.mock import patch

from tests.test_v2_bridge import IsolatedBridgeTestCase, handshake_payload
from autoftbq_v2.bridge.service import BridgeService
from autoftbq_v2.bridge.live_agent import LiveProjectAgentTask, LiveProjectAgent
from autoftbq_v2.ftb_store import FTBQuestStore
from snbt_parser import parse_snbt


class LiveAgentTests(IsolatedBridgeTestCase):
    def test_validated_tool_is_published_before_model_finishes(self):
        service, sid, record = self.setup_request("创建章节")
        task = LiveProjectAgentTask(service, record, service.agent_context(sid), None)
        store = FTBQuestStore.create_new()
        task.stream_base, task.stream_revision = store._project_payload(), "rev"
        agent = LiveProjectAgent(task, store, None)
        agent.prepare_run("创建章节")
        agent._begin_transaction()
        def receipt(operations, revision):
            self.assertTrue(operations)
            self.assertEqual(revision, "rev")
            task.applied_batches += 1
            return "rev2", deepcopy(store._project_payload())
        with patch.object(task, "apply_batch", side_effect=receipt) as submit:
            result = json.loads(agent.call_tool("create_chapter", {"title": "实时章节"}))
            self.assertIn("chapter_id", result)
            submit.assert_called_once()
        self.assertEqual(task.stream_revision, "rev2")
        self.assertTrue(agent.applied_actions)
        # A later local rollback must not remove the server-confirmed chapter.
        agent.rollback_transaction()
        self.assertIn(result["chapter_id"], [c.id for c in store.project.chapters])

    def test_pause_resume_and_cancel_do_not_lose_request(self):
        service, sid, record = self.setup_request("创建章节")
        task = LiveProjectAgentTask(service, record, service.agent_context(sid), None)
        service.requests.set_paused(record.id, True)
        self.assertTrue(service.requests.public(record.id)["pause_requested"])
        def resume(_seconds):
            self.assertEqual(service.requests.public(record.id)["progress"]["stage"], "paused")
            service.requests.set_paused(record.id, False)
        with patch("autoftbq_v2.bridge.live_agent.time.sleep", side_effect=resume):
            task.check_active()
        self.assertFalse(service.requests.is_paused(record.id))
        service.requests.set_paused(record.id, True)
        service.requests.cancel(record.id)
        with self.assertRaises(InterruptedError):
            task.check_active()

    def test_failed_live_publish_prevents_followup_writes(self):
        service, sid, record = self.setup_request("创建章节")
        task = LiveProjectAgentTask(service, record, service.agent_context(sid), None)
        store = FTBQuestStore.create_new()
        task.stream_base, task.stream_revision = store._project_payload(), "rev"
        agent = LiveProjectAgent(task, store, None)
        agent.prepare_run("创建章节")
        agent._begin_transaction()
        with patch.object(task, "apply_batch", side_effect=ValueError("服务器拒绝")) as submit:
            with self.assertRaisesRegex(ValueError, "服务器拒绝"):
                agent.call_tool("create_chapter", {"title": "测试"})
            with self.assertRaisesRegex(ValueError, "服务器拒绝"):
                agent.call_tool("create_chapter", {"title": "不应再次提交"})
            submit.assert_called_once()

    def test_evidence_tool_is_read_only_and_preserves_pagination_and_unknowns(self):
        service, sid, record = self.setup_request("查询物品来源")
        task = LiveProjectAgentTask(service, record, service.agent_context(sid), None)
        agent = LiveProjectAgent(task, FTBQuestStore.create_new(), None)
        before = agent.store._project_payload()
        expected = {"status": "ok", "data_version": "world:2", "coverage": "partial",
                    "availability": "unknown", "data": {"recipes": [], "has_more": True, "next_offset": 200}}
        args = {"kind": "recipes", "item_id": "minecraft:diamond", "offset": 100, "data_version": "world:2"}
        with patch.object(task, "query", return_value=expected) as query:
            response = json.loads(agent.call_tool("inspect_game_data", args))
            query.assert_called_once_with("inspect_game_data", args)
        self.assertEqual(response, expected)
        self.assertEqual(before, agent.store._project_payload())
        self.assertTrue(agent.tool_registry.is_read_only("inspect_game_data"))
        self.assertIn("inspect_game_data", agent._model_tool_names("创建主线"))
    def setup_request(self, prompt):
        service = BridgeService()
        sid = service.handshake(handshake_payload())["session_id"]
        service.update_context({"session_id": sid, "revision": 1, "world_id": "world",
            "book_revision": "rev", "server_book_revision": "rev", "chapter": {},
            "selected_chapters": [], "selected_quests": [],
            "book_summary": {"server_can_edit": True}, "registry_summary": {}})
        service.save_book_snapshot({"session_id": sid, "book_revision": "rev",
            "format": "ftbquests-snbt-v1", "snapshot": {"title": "Live", "documents": [], "chapters": []}})
        service.submit_request({"session_id": sid, "context_revision": 1, "prompt": prompt})
        record = service.requests.take_next()
        return service, sid, record

    def test_game_uses_project_tools_and_continues_after_partial_batch(self):
        service, sid, record = self.setup_request("创建一个章节，添加6个勾选任务，不要连线")
        calls = []
        class Client:
            chapter = None
            def chat_with_tools(self, messages, tools, handler, **kwargs):
                names = {t["function"]["name"] for t in tools}
                assert "add_quest_chain" in names
                assert "propose_changes" not in names
                if self.chapter is None:
                    value = json.loads(handler("create_chapter", {"title": "主线"}))
                    self.chapter = value["chapter_id"]
                for _ in range(2):
                    value = json.loads(handler("add_quest", {"chapter_id": self.chapter,
                        "title": "任务", "task_type": "checkmark", "description": "完成此步骤"}))
                    assert "quest_id" in value, value
                calls.append(1)
                return "本批完成", False
        task = LiveProjectAgentTask(service, record, service.agent_context(sid), Client())
        task.streaming_enabled = False  # exercise the legacy end-of-round batching path
        # Simulate server normalization/readback, independently applying raw operations.
        actual = {"format": "autoftbq-v2", "format_version": 2,
            "project": {"title": "Live", "mod_folder": ""},
            "documents": {"data.snbt": {"version": 13}, "chapter_groups.snbt": {"chapter_groups": []}}, "chapters": []}
        batches = []
        def apply(operations, revision):
            batches.append(operations)
            for op in operations:
                kind = op["kind"]
                raw = parse_snbt(op["data_snbt"]) if "data_snbt" in op else None
                if kind == "upsert_chapter_raw":
                    raw["quests"] = []
                    actual["chapters"].append(raw)
                elif kind == "upsert_quest_raw":
                    ch = next(c for c in actual["chapters"] if c["id"] == op["chapter_id"])
                    ch["quests"].append(raw)
                elif kind == "upsert_quest_object_raw":
                    q = next(q for c in actual["chapters"] for q in c["quests"] if q["id"] == op["quest_id"])
                    q.setdefault("tasks" if op["object_kind"] == "task" else "rewards", []).append(raw)
                elif kind == "update_book_raw":
                    actual["documents"]["data.snbt"] = raw
            task.applied_batches += 1
            return "rev" + str(len(batches)), deepcopy(actual)
        with patch.object(task, "apply_batch", side_effect=apply):
            task.run()
        state = service.requests.public(record.id)
        self.assertEqual(state["outcome"], "applied", state)
        self.assertEqual(len(batches), 2)
        self.assertEqual(sum(len(c["quests"]) for c in actual["chapters"]), 6)
        checkpoint = service.shared_state.latest_agent_checkpoint(record.conversation_id)
        self.assertEqual(checkpoint["plan"]["phase"], "completed")

    def test_no_progress_stops_and_persists_unfinished_plan(self):
        service, sid, record = self.setup_request("添加6个任务")
        class Client:
            def chat_with_tools(self, *args, **kwargs):
                return "完成了", False
        LiveProjectAgentTask(service, record, service.agent_context(sid), Client()).run()
        state = service.requests.public(record.id)
        self.assertEqual(state["outcome"], "needs_attention")
        self.assertIsNotNone(service.shared_state.latest_agent_checkpoint(record.conversation_id))

    def test_cancelled_request_does_not_queue_new_batch(self):
        service, sid, record = self.setup_request("添加任务")
        task = LiveProjectAgentTask(service, record, service.agent_context(sid), None)
        service.requests.cancel(record.id)
        with patch.object(service.requests, "create_studio_transaction") as queue:
            with self.assertRaises(InterruptedError):
                task.apply_batch([], "rev")
            queue.assert_not_called()

    def test_batch_failure_keeps_server_reason(self):
        service, sid, record = self.setup_request("创建章节")
        task = LiveProjectAgentTask(service, record, service.agent_context(sid), None)
        with patch.object(service.requests, "public_proposal", return_value={
            "status": "failed", "application_message": "写入已回滚：找不到章节：ABC"}):
            with self.assertRaisesRegex(ValueError, "找不到章节：ABC"):
                task.apply_batch([{"kind": "create_chapter", "temp_id": "ch", "title": "测试"}], "rev")

    def test_batch_waits_for_snapshot_matching_server_receipt(self):
        service, sid, record = self.setup_request("创建章节")
        context = service.agent_context(sid)
        task = LiveProjectAgentTask(service, record, context, None)
        before = service.book_snapshot(sid)
        after = deepcopy(before)
        after["book_revision"] = "rev2"
        updated = dict(context, book_revision="rev2", server_book_revision="rev2")
        with patch.object(service, "context", side_effect=[context, context, updated, updated]), \
             patch.object(service.requests, "public_proposal", return_value={"status": "applied", "applied_book_revision": "rev2"}), \
             patch.object(service, "book_snapshot", side_effect=[before, after]) as snapshots, \
             patch("autoftbq_v2.bridge.live_agent.time.sleep"):
            revision, payload = task.apply_batch([{"kind": "create_chapter", "temp_id": "ch", "title": "测试"}], "rev")
        self.assertEqual(revision, "rev2")
        self.assertEqual(snapshots.call_count, 2)
        self.assertEqual(task.applied_batches, 1)
