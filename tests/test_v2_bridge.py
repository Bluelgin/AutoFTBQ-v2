import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from autoftbq_v2.bridge.protocol import GameContext, Handshake, ProtocolError
from autoftbq_v2.bridge.server import StudioBridgeServer
from autoftbq_v2.bridge.game_agent import (
    GameAgentTask, game_agent_messages, is_edit_request,
)
from autoftbq_v2.bridge.request_manager import GameRequestManager
from autoftbq_v2.bridge.service import BridgeService
from autoftbq_v2.bridge.shared_state import SharedProjectState
from autoftbq_v2.bridge.book_sync import diff_project_payload, snapshot_to_project_payload
from autoftbq_v2.bridge.selection_scope import validate_game_selection_scope


def handshake_payload(**changes):
    value = {
        "protocol_version": 1,
        "client_id": "test-client",
        "minecraft_version": "1.20.1",
        "loader": {"name": "forge", "version": "47.2.19"},
        "ftb_quests_version": "2001.4.22",
        "mod_version": "0.1.0",
        "capabilities": [
            "context.chapter", "context.selected_quests",
            "context.selected_chapters", "context.agent_selection.v1",
            "scope.enforced.v1",
            "request.preflight_sync.v1",
            "request.generation_recovery.v1",
            "agent.shared_core.v1",
            "data.evidence.v1",
            "transaction.strict_snbt.v1",
            "transaction.batch_index.v1",
            "agent.live_steps.v1",
            "result.server_truth.v1",
            "revision.network_fingerprint.v1",
            "agent.transactional_edit", "project.timeline.v1",
            "project.snapshot.v1", "write.auto_apply.v1",
            "game_query.registry_batch", "game_query.registry_validate",
        ],
    }
    value.update(changes)
    return value


class IsolatedBridgeTestCase(unittest.TestCase):
    def setUp(self):
        self._state_root = tempfile.TemporaryDirectory()
        self._old_state_path = os.environ.get("AUTOFTBQ_STATE_PATH")
        os.environ["AUTOFTBQ_STATE_PATH"] = os.path.join(
            self._state_root.name, "studio-bridge.sqlite3",
        )

    def tearDown(self):
        if self._old_state_path is None:
            os.environ.pop("AUTOFTBQ_STATE_PATH", None)
        else:
            os.environ["AUTOFTBQ_STATE_PATH"] = self._old_state_path
        self._state_root.cleanup()


class BridgeProtocolTests(IsolatedBridgeTestCase):
    def test_handshake_is_versioned_and_loader_neutral(self):
        parsed = Handshake.parse(handshake_payload())
        self.assertEqual(parsed.minecraft_version, "1.20.1")
        self.assertEqual(parsed.loader.name, "forge")

    def test_game_agent_treats_edit_request_as_authorization(self):
        system = game_agent_messages("do it now", {})[0]["content"]
        self.assertIn("Never ask for confirmation", system)
        self.assertIn("must be executed immediately", system)
        self.assertTrue(is_edit_request("do it now"))
        self.assertTrue(is_edit_request("把这些无效任务删除"))
        self.assertFalse(is_edit_request("这些任务有什么问题？"))

    def test_core_task_reward_and_description_operations_are_bounded(self):
        operations = [
            {"kind": "update_quest", "quest_id": "ABC", "changes": {
                "description": ["第一段", "第二段"],
            }},
            {"kind": "add_checkmark_task", "quest_id": "ABC"},
            {"kind": "add_xp_task", "quest_id": "ABC", "amount": 250},
            {"kind": "add_xp_reward", "quest_id": "ABC", "amount": 100},
            {"kind": "add_xp_levels_reward", "quest_id": "ABC", "amount": 3},
        ]
        clean = [GameRequestManager._validate_operation(value) for value in operations]
        self.assertEqual(clean, operations)
        with self.assertRaises(ProtocolError):
            GameRequestManager._validate_operation({
                "kind": "add_xp_reward", "quest_id": "ABC", "amount": 0,
            })
        with self.assertRaises(ProtocolError):
            GameRequestManager._validate_operation({
                "kind": "update_quest", "quest_id": "ABC",
                "changes": {"description": ["x" * 4001]},
            })

        with self.assertRaises(ProtocolError):
            Handshake.parse(handshake_payload(protocol_version=2))

    def test_proposal_transport_limit_matches_game_packet_limit(self):
        small = [{"kind": "update_quest", "quest_id": "ABC", "changes": {
            "title": "正常标题",
        }}]
        oversized = [{"kind": "upsert_quest_raw", "quest_id": "ABC",
                      "chapter_id": "DEF", "data_snbt": "x" * 260_000}]
        self.assertTrue(GameRequestManager._proposal_fits_transport(small))
        self.assertFalse(GameRequestManager._proposal_fits_transport(oversized))

    def test_context_rejects_unbounded_selection(self):
        with self.assertRaises(ProtocolError):
            GameContext.parse({
                "session_id": "session",
                "revision": 1,
                "selected_quests": [
                    {"id": str(index), "title": "", "x": 0, "y": 0}
                    for index in range(257)
                ],
            })

    def test_context_parses_explicit_chapter_and_quest_scope(self):
        context = GameContext.parse({
            "session_id": "session", "revision": 1,
            "chapter": {"id": "AAA", "title": "Viewed"},
            "selected_chapters": [{
                "id": "ABC", "title": "Main", "quest_ids": ["DEF", "123"],
            }],
            "selected_quests": [{
                "id": "FED", "title": "One", "chapter_id": "CBA", "x": 1, "y": 2,
            }],
        })
        self.assertEqual(context.selected_chapters[0].quest_ids, ("DEF", "123"))
        self.assertEqual(context.selected_quests[0].chapter_id, "CBA")

    def test_explicit_game_scope_rejects_out_of_selection_writes(self):
        context = {
            "selected_chapters": [{"id": "ABC", "quest_ids": ["DEF"]}],
            "selected_quests": [{"id": "FED", "chapter_id": "CBA"}],
            "selected_chapter_details": [{"id": "ABC", "quests": [{
                "id": "DEF", "chapter_id": "ABC", "task_ids": ["TASK1"],
            }]}],
        }
        validate_game_selection_scope(context, [
            {"kind": "update_quest", "quest_id": "DEF", "changes": {"title": "New"}},
            {"kind": "create_quest", "temp_id": "new_one", "chapter_id": "ABC",
             "title": "New", "x": 0, "y": 0},
            {"kind": "add_checkmark_task", "quest_id": "new_one"},
            {"kind": "remove_quest_object", "object_id": "TASK1"},
        ])
        with self.assertRaisesRegex(ProtocolError, "未加入 Agent 上下文"):
            validate_game_selection_scope(context, [{
                "kind": "update_quest", "quest_id": "OTHER", "changes": {"title": "No"},
            }])
        with self.assertRaisesRegex(ProtocolError, "超出当前 Agent 选区"):
            validate_game_selection_scope(context, [{
                "kind": "create_chapter", "temp_id": "new", "title": "No",
            }])

    def test_studio_rejects_legacy_game_jar_without_shared_project_protocol(self):
        value = handshake_payload(capabilities=["agent.read_only", "proposal.preview"])
        with self.assertRaisesRegex(ProtocolError, "版本过旧"):
            BridgeService().handshake(value)

    def test_legacy_generic_world_project_migrates_to_stable_world_identity(self):
        state = SharedProjectState()
        legacy = state.resolve_project("client", "singleplayer")
        migrated = state.resolve_project("client", "singleplayer:abc123")
        other = state.resolve_project("client", "singleplayer:def456")
        self.assertEqual(migrated["project_id"], legacy["project_id"])
        self.assertNotEqual(other["project_id"], migrated["project_id"])


class BridgeServerTests(IsolatedBridgeTestCase):
    def _request(self, server, path, payload=None, token=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"http://127.0.0.1:{server.port}{path}", data=data, headers=headers,
            method="POST" if payload is not None else "GET",
        )
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_server_writes_discovery_and_accepts_context(self):
        with tempfile.TemporaryDirectory() as root:
            discovery = os.path.join(root, "bridge.json")
            with StudioBridgeServer(discovery_path=discovery) as server:
                saved = json.loads(Path(discovery).read_text(encoding="utf-8"))
                self.assertEqual(saved["port"], server.port)
                self.assertEqual(saved["host"], "127.0.0.1")

                _, handshake = self._request(
                    server, "/v1/handshake", handshake_payload(), server.token,
                )
                session_id = handshake["session_id"]
                _, accepted = self._request(server, "/v1/context", {
                    "session_id": session_id,
                    "revision": 3,
                    "world_id": "singleplayer:test",
                    "chapter": {"id": "ABC", "title": "主线"},
                    "selected_quests": [
                        {"id": "DEF", "title": "第一步", "x": 1.5, "y": -2},
                    ],
                    "book_summary": {"chapters": 1, "quests": 1},
                    "registry_summary": {"items": 1200},
                }, server.token)
                self.assertEqual(accepted["revision"], 3)
                _, context = self._request(
                    server, f"/v1/context?session_id={session_id}", token=server.token,
                )
                self.assertEqual(context["chapter_title"], "主线")
                self.assertEqual(context["selected_quests"][0]["id"], "DEF")
                snapshot = server.service.snapshot()
                self.assertEqual(snapshot["loader"], "forge")
                self.assertEqual(snapshot["selected_quests"], 1)
            self.assertFalse(os.path.exists(discovery))

    def test_server_rejects_missing_token(self):
        with tempfile.TemporaryDirectory() as root:
            with StudioBridgeServer(discovery_path=os.path.join(root, "bridge.json")) as server:
                with self.assertRaises(HTTPError) as raised:
                    self._request(server, "/v1/handshake", handshake_payload())
                self.assertEqual(raised.exception.code, 401)

    def test_request_requires_latest_context_and_can_be_cancelled(self):
        service = BridgeService()
        session_id = service.handshake(handshake_payload())["session_id"]
        service.update_context({
            "session_id": session_id, "revision": 4,
            "chapter": {}, "selected_quests": [],
            "book_summary": {}, "registry_summary": {},
        })

        with self.assertRaises(ProtocolError):
            service.submit_request({
                "session_id": session_id, "context_revision": 3, "prompt": "检查任务",
            })

        submitted = service.submit_request({
            "session_id": session_id, "context_revision": 4, "prompt": "检查任务",
        })
        cancelled = service.requests.cancel(submitted["request_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNone(service.requests.take_next())

    def test_handshake_waits_for_world_before_binding_project(self):
        service = BridgeService()
        handshake = service.handshake(handshake_payload())
        self.assertTrue(handshake["project_pending"])
        self.assertEqual(handshake["project_id"], "")
        bound = service.update_context({
            "session_id": handshake["session_id"], "revision": 1,
            "world_id": "singleplayer:stable-world", "chapter": {},
            "selected_quests": [], "book_summary": {}, "registry_summary": {},
        })
        self.assertTrue(bound["project_id"])
        self.assertTrue(bound["conversation_id"])

    def test_request_queue_has_a_hard_bound(self):
        manager = GameRequestManager()
        for index in range(manager.MAX_REQUESTS):
            manager.submit(f"session-{index}", f"请求 {index}", 1)
        with self.assertRaises(ProtocolError):
            manager.submit("overflow", "超出上限", 1)

    def test_session_rejects_a_second_non_terminal_request(self):
        manager = GameRequestManager()
        first = manager.submit("session", "第一项", 1)
        with self.assertRaisesRegex(ProtocolError, "已有 Agent 请求"):
            manager.submit("session", "第二项", 1)
        manager.cancel(first["request_id"])
        self.assertEqual(manager.submit("session", "取消后重试", 1)["status"], "queued")

    def test_identical_game_query_is_cached_and_counts_once(self):
        manager = GameRequestManager()
        submitted = manager.submit("session", "核对物品", 1)
        record = manager.take_next()
        received = {}

        def first_query():
            received["first"] = manager.request_game_query(
                record.id, "session", "validate_registry_ids",
                {"registry": "item", "ids": ["minecraft:stone"]}, timeout=2,
            )

        waiter = threading.Thread(target=first_query)
        waiter.start()
        query = None
        for _ in range(40):
            query = manager.take_game_query("session")
            if query:
                break
            __import__("time").sleep(0.025)
        self.assertIsNotNone(query)
        manager.resolve_game_query("session", query["query_id"], {
            "results": [{"id": "minecraft:stone", "exists": True}],
        })
        waiter.join(2)
        second = manager.request_game_query(
            record.id, "session", "validate_registry_ids",
            {"registry": "item", "ids": ["minecraft:stone"]}, timeout=1,
        )
        self.assertEqual(received["first"], second)
        self.assertEqual(manager.query_usage(submitted["request_id"]), (1, 12))
        self.assertIsNone(manager.take_game_query("session"))

    def test_restart_marks_old_timeline_request_interrupted(self):
        path = os.environ["AUTOFTBQ_STATE_PATH"]
        state = SharedProjectState(path)
        project = state.resolve_project("test-client", "singleplayer:resume")
        state.append_event(
            project["project_id"], project["conversation_id"], "chat.user", "game",
            {"request_id": "stale-request", "text": "旧请求"},
        )
        service = BridgeService(shared_state=SharedProjectState(path))
        handshake = service.handshake(handshake_payload())
        service.update_context({
            "session_id": handshake["session_id"], "revision": 1,
            "world_id": "singleplayer:resume", "chapter": {},
            "selected_quests": [], "book_summary": {}, "registry_summary": {},
        })
        kinds = [event["kind"] for event in service.events(handshake["session_id"])]
        self.assertEqual(kinds, ["chat.user", "work.interrupted"])

    def test_bridge_shutdown_finishes_active_request(self):
        service = BridgeService()
        handshake = service.handshake(handshake_payload())
        service.update_context({
            "session_id": handshake["session_id"], "revision": 1,
            "world_id": "singleplayer:shutdown", "chapter": {},
            "selected_quests": [], "book_summary": {}, "registry_summary": {},
        })
        submitted = service.submit_request({
            "session_id": handshake["session_id"], "context_revision": 1,
            "prompt": "长任务",
        })
        with tempfile.TemporaryDirectory() as root:
            server = StudioBridgeServer(
                discovery_path=os.path.join(root, "bridge.json"), service=service,
            ).start()
            server.stop()
        result = service.requests.public(submitted["request_id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("Studio 已关闭", result["error"])

    def test_http_request_status_cancel_and_game_query_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            with StudioBridgeServer(discovery_path=os.path.join(root, "bridge.json")) as server:
                _, handshake = self._request(
                    server, "/v1/handshake", handshake_payload(), server.token,
                )
                session_id = handshake["session_id"]
                self._request(server, "/v1/context", {
                    "session_id": session_id, "revision": 1,
                    "chapter": {}, "selected_quests": [],
                    "book_summary": {}, "registry_summary": {},
                }, server.token)
                _, submitted = self._request(server, "/v1/requests", {
                    "session_id": session_id, "context_revision": 1,
                    "prompt": "检查当前任务",
                }, server.token)
                request_id = submitted["request_id"]

                _, queued = self._request(
                    server, f"/v1/requests/{request_id}", token=server.token,
                )
                self.assertEqual(queued["status"], "queued")
                _, cancelled = self._request(
                    server, f"/v1/requests/{request_id}/cancel", {}, server.token,
                )
                self.assertEqual(cancelled["status"], "cancelled")
                _, history = self._request(
                    server, f"/v1/requests?session_id={session_id}&limit=10",
                    token=server.token,
                )
                self.assertEqual(history["requests"][0]["request_id"], request_id)

                second = server.service.submit_request({
                    "session_id": session_id, "context_revision": 1,
                    "prompt": "查询 registry",
                })
                record = server.service.requests.take_next()
                received = {}

                def wait_for_result():
                    received.update(server.service.requests.request_game_query(
                        record.id, session_id, "search_registry",
                        {"registry": "item", "query": "shaft", "limit": 5},
                        timeout=2,
                    ))

                waiter = threading.Thread(target=wait_for_result)
                waiter.start()
                query = None
                for _ in range(40):
                    _, envelope = self._request(
                        server, f"/v1/game-queries/next?session_id={session_id}",
                        token=server.token,
                    )
                    query = envelope["query"]
                    if query is not None:
                        break
                    __import__("time").sleep(0.025)
                self.assertIsNotNone(query)
                _, accepted = self._request(
                    server, f"/v1/game-queries/{query['query_id']}/result", {
                        "session_id": session_id,
                        "result": {"matches": [{"id": "create:shaft"}]},
                    }, server.token,
                )
                waiter.join(2)
                self.assertTrue(accepted["accepted"])
                self.assertEqual(received["matches"][0]["id"], "create:shaft")
                self.assertEqual(second["status"], "queued")

    def test_read_only_agent_round_trips_a_game_query(self):
        class ToolClient:
            def chat_with_tools(self, _messages, tools, handler, **_kwargs):
                self.max_rounds = _kwargs.get("max_rounds")
                self.assert_tool_names = {
                    value["function"]["name"] for value in tools
                }
                result = json.loads(handler("search_registry", {
                    "registry": "item", "query": "shaft", "limit": 5,
                }))
                return f"找到 {result['matches'][0]['id']}"

        service = BridgeService()
        session_id = service.handshake(handshake_payload())["session_id"]
        service.update_context({
            "session_id": session_id, "revision": 1,
            "chapter": {"id": "ABC", "title": "主线"},
            "selected_quests": [], "book_summary": {}, "registry_summary": {},
        })
        submitted = service.submit_request({
            "session_id": session_id, "context_revision": 1, "prompt": "查询传动杆",
        })
        record = service.requests.take_next()
        client = ToolClient()
        task = GameAgentTask(service, record, service.context(session_id), client)
        task.start()

        query = None
        for _ in range(40):
            query = service.requests.take_game_query(session_id)
            if query:
                break
            __import__("time").sleep(0.025)
        self.assertIsNotNone(query)
        self.assertEqual(query["name"], "search_registry")
        self.assertTrue(service.requests.resolve_game_query(session_id, query["query_id"], {
            "matches": [{"id": "create:shaft", "name": "传动杆"}],
        }))
        task.join(2)

        result = service.requests.public(submitted["request_id"])
        self.assertEqual(result["status"], "completed")
        self.assertIn("create:shaft", result["result"])
        self.assertEqual(client.assert_tool_names, {
            "get_selected_quest_details", "search_registry", "search_registry_batch",
            "validate_registry_ids", "search_recipes", "propose_changes",
        })
        self.assertEqual(client.max_rounds, 10)

    def test_game_agent_receives_bounded_same_session_history(self):
        class HistoryClient:
            def chat_with_tools(self, messages, _tools, _handler, **_kwargs):
                self.messages = messages
                return "第二轮回答"

        service = BridgeService()
        session_id = service.handshake(handshake_payload())["session_id"]
        service.update_context({
            "session_id": session_id, "revision": 1,
            "chapter": {}, "selected_quests": [],
            "book_summary": {}, "registry_summary": {},
        })
        first = service.submit_request({
            "session_id": session_id, "context_revision": 1, "prompt": "第一轮问题",
        })
        service.requests.take_next()
        service.requests.complete(first["request_id"], "第一轮回答")
        service.submit_request({
            "session_id": session_id, "context_revision": 1, "prompt": "继续解释",
        })
        second = service.requests.take_next()
        client = HistoryClient()
        task = GameAgentTask(service, second, service.context(session_id), client)
        task.start()
        task.join(2)
        contents = [value["content"] for value in client.messages]
        self.assertIn("第一轮问题", contents)
        self.assertIn("第一轮回答", contents)
        self.assertIn("继续解释", contents[-1])

    def test_agent_creates_review_only_proposal_and_http_confirms_it(self):
        class ProposalClient:
            def chat_with_tools(self, _messages, _tools, handler, **_kwargs):
                created = json.loads(handler("propose_changes", {
                    "summary": "新增一个入门任务",
                    "operations": [{
                        "kind": "create_quest", "temp_id": "quest_intro",
                        "chapter_id": "ABC", "title": "制作传动杆",
                        "x": 1, "y": 2,
                    }, {
                        "kind": "add_item_task", "quest_id": "quest_intro",
                        "item_id": "create:shaft", "count": 8,
                    }],
                }))
                return f"已生成提案 {created['proposal_id']}，尚未应用。"

        with tempfile.TemporaryDirectory() as root:
            with StudioBridgeServer(discovery_path=os.path.join(root, "bridge.json")) as server:
                _, handshake = self._request(
                    server, "/v1/handshake", handshake_payload(), server.token,
                )
                session_id = handshake["session_id"]
                self._request(server, "/v1/context", {
                    "session_id": session_id, "revision": 7,
                    "book_revision": "book-revision-a",
                    "server_book_revision": "book-revision-a",
                    "chapter": {"id": "ABC", "title": "主线"},
                    "selected_quests": [],
                    "book_summary": {"can_edit": True, "server_can_edit": True},
                    "registry_summary": {},
                }, server.token)
                submitted = server.service.submit_request({
                    "session_id": session_id, "context_revision": 7,
                    "prompt": "新增一个制作传动杆的任务",
                })
                record = server.service.requests.take_next()
                task = GameAgentTask(
                    server.service, record, server.service.context(session_id), ProposalClient(),
                )
                task.start()
                task.join(2)

                state = server.service.requests.public(submitted["request_id"])
                self.assertEqual(state["status"], "completed")
                self.assertTrue(state["proposal_id"])
                _, proposal = self._request(
                    server, f"/v1/proposals/{state['proposal_id']}", token=server.token,
                )
                self.assertEqual(proposal["status"], "proposed")
                self.assertEqual(proposal["operations"][1]["item_id"], "create:shaft")
                _, confirmed = self._request(
                    server, f"/v1/proposals/{state['proposal_id']}/confirm", {
                        "session_id": session_id, "context_revision": 7,
                    }, server.token,
                )
                self.assertEqual(confirmed["status"], "confirmed")
                _, applied = self._request(
                    server, f"/v1/proposals/{state['proposal_id']}/application", {
                        "session_id": session_id, "status": "applied",
                        "message": "服务器事务已提交",
                        "server_book_revision": "book-revision-b",
                        "id_map": {"quest_intro": "1234ABCD"},
                    }, server.token,
                )
                self.assertEqual(applied["status"], "applied")
                self.assertEqual(applied["id_map"]["quest_intro"], "1234ABCD")
                self.assertEqual(
                    server.service.requests.public(submitted["request_id"])["outcome"],
                    "applied",
                )
                _, replayed = self._request(
                    server, f"/v1/proposals/{state['proposal_id']}/application", {
                        "session_id": session_id, "status": "applied",
                        "message": "服务器事务已提交",
                        "server_book_revision": "book-revision-b",
                        "id_map": {"quest_intro": "1234ABCD"},
                    }, token=server.token,
                )
                self.assertEqual(replayed, applied)
                _, undone = self._request(
                    server, f"/v1/proposals/{state['proposal_id']}/application", {
                        "session_id": session_id, "status": "undone",
                        "message": "服务器事务已撤销",
                        "server_book_revision": "book-revision-a",
                        "id_map": {},
                    }, server.token,
                )
                self.assertEqual(undone["status"], "undone")
                self.assertEqual(
                    server.service.requests.public(submitted["request_id"])["outcome"],
                    "undone",
                )

    def test_edit_request_auto_continues_when_model_asks_for_confirmation(self):
        class ConfirmationClient:
            def __init__(self):
                self.calls = 0

            def chat_with_tools(self, _messages, _tools, handler, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return "要现在开始修改吗？"
                created = json.loads(handler("propose_changes", {
                    "summary": "直接更新任务",
                    "operations": [{
                        "kind": "update_quest", "quest_id": "DEF",
                        "changes": {"title": "已更新"},
                    }],
                }))
                return f"已生成事务 {created['proposal_id']}"

        service = BridgeService()
        session_id = service.handshake(handshake_payload())["session_id"]
        service.update_context({
            "session_id": session_id, "revision": 1,
            "book_revision": "rev", "server_book_revision": "rev",
            "chapter": {}, "selected_chapters": [], "selected_quests": [],
            "book_summary": {"server_can_edit": True}, "registry_summary": {},
        })
        submitted = service.submit_request({
            "session_id": session_id, "context_revision": 1,
            "prompt": "把这个任务标题修改掉",
        })
        record = service.requests.take_next()
        client = ConfirmationClient()
        task = GameAgentTask(service, record, service.context(session_id), client)
        task.start()
        task.join(2)

        state = service.requests.public(submitted["request_id"])
        self.assertEqual(client.calls, 2)
        self.assertTrue(state["proposal_id"])
        self.assertEqual(state["status"], "completed")

    def test_edit_request_without_transaction_never_claims_success(self):
        class ReadOnlyClient:
            def __init__(self):
                self.calls = 0

            def chat_with_tools(self, _messages, _tools, _handler, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return "检查完成，等待下一步。"
                return "工具操作已完成，请在编辑器中检查结果。"

        service = BridgeService()
        session_id = service.handshake(handshake_payload())["session_id"]
        service.update_context({
            "session_id": session_id, "revision": 1,
            "book_revision": "rev", "server_book_revision": "rev",
            "chapter": {}, "selected_chapters": [], "selected_quests": [],
            "book_summary": {"server_can_edit": True}, "registry_summary": {},
        })
        submitted = service.submit_request({
            "session_id": session_id, "context_revision": 1,
            "prompt": "修复这些任务并立即应用",
        })
        record = service.requests.take_next()
        client = ReadOnlyClient()
        task = GameAgentTask(service, record, service.context(session_id), client)
        task.start()
        task.join(2)

        state = service.requests.public(submitted["request_id"])
        self.assertEqual(client.calls, 2)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["outcome"], "no_changes")
        self.assertEqual(state["proposal_id"], "")
        self.assertIn("任务书没有发生变化", state["result"])
        self.assertNotIn("操作已完成", state["result"])

    def test_transaction_continuation_reuses_query_trace_and_forces_proposal(self):
        class TraceClient:
            def __init__(self):
                self.calls = 0

            def chat_with_tools(self, messages, tools, handler, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    kwargs["trace_sink"].append({
                        "tool": "validate_registry_ids", "arguments": {},
                        "result": {"valid": ["minecraft:diamond"]},
                    })
                    return "模型输出预算已耗尽", True
                self.second_messages = messages
                self.second_tools = tools
                self.second_kwargs = kwargs
                created = json.loads(handler("propose_changes", {
                    "summary": "复用查询结果更新图标",
                    "operations": [{
                        "kind": "update_quest", "quest_id": "DEF",
                        "changes": {"icon": "minecraft:diamond"},
                    }],
                }))
                return f"已生成事务 {created['proposal_id']}", False

        service = BridgeService()
        session_id = service.handshake(handshake_payload())["session_id"]
        service.update_context({
            "session_id": session_id, "revision": 1,
            "book_revision": "rev", "server_book_revision": "rev",
            "chapter": {}, "selected_chapters": [], "selected_quests": [],
            "book_summary": {"server_can_edit": True}, "registry_summary": {},
        })
        submitted = service.submit_request({
            "session_id": session_id, "context_revision": 1,
            "prompt": "检查并替换这个任务图标",
        })
        record = service.requests.take_next()
        client = TraceClient()
        task = GameAgentTask(service, record, service.context(session_id), client)
        task.start()
        task.join(2)

        state = service.requests.public(submitted["request_id"])
        self.assertTrue(state["proposal_id"])
        self.assertEqual(state["outcome"], "proposal_prepared")
        self.assertIn("minecraft:diamond", client.second_messages[-1]["content"])
        self.assertEqual(client.second_kwargs["tool_choice"], "required")
        self.assertEqual(
            [tool["function"]["name"] for tool in client.second_tools],
            ["propose_changes"],
        )

    def test_invalid_quests_cannot_be_silently_replaced_by_empty_chapter(self):
        results = []
        class Client:
            def chat_with_tools(self, messages, tools, handler, **kwargs):
                chapter = {"kind": "create_chapter", "temp_id": "ch", "title": "主线"}
                quest = {"kind": "create_quest", "temp_id": "q", "chapter_id": "ch", "title": "开始"}
                for ops in ([chapter, quest], [chapter],
                            [chapter, dict(quest, x=0, y=0), {"kind": "add_checkmark_task", "quest_id": "q"}]):
                    results.append(json.loads(handler("propose_changes", {"summary": "生成主线", "operations": ops})))
                return "已准备事务", False
        service = BridgeService()
        sid = service.handshake(handshake_payload())["session_id"]
        service.update_context({
            "session_id": sid, "revision": 1, "book_revision": "rev", "server_book_revision": "rev",
            "chapter": {}, "selected_chapters": [], "selected_quests": [],
            "book_summary": {"server_can_edit": True}, "registry_summary": {},
        })
        service.submit_request({"session_id": sid, "context_revision": 1, "prompt": "创建主线任务"})
        record = service.requests.take_next()
        GameAgentTask(service, record, service.context(sid), Client()).run()
        self.assertIn("operations[1]", results[0]["error"])
        self.assertIn("missing=['x', 'y']", results[0]["error"])
        self.assertIn("Incomplete repair", results[1]["error"])
        self.assertTrue(results[2]["accepted"])
        proposal = service.requests.public_proposal(results[2]["proposal_id"])
        self.assertEqual(len(proposal["operations"]), 3)

    def test_transaction_budget_exhaustion_is_reported_explicitly(self):
        class ExhaustedClient:
            def chat_with_tools(self, _messages, _tools, _handler, **_kwargs):
                return "模型输出预算已耗尽", True

        service = BridgeService()
        session_id = service.handshake(handshake_payload())["session_id"]
        service.update_context({
            "session_id": session_id, "revision": 1,
            "book_revision": "rev", "server_book_revision": "rev",
            "chapter": {}, "selected_chapters": [], "selected_quests": [],
            "book_summary": {"server_can_edit": True}, "registry_summary": {},
        })
        submitted = service.submit_request({
            "session_id": session_id, "context_revision": 1,
            "prompt": "批量修复这些任务",
        })
        record = service.requests.take_next()
        task = GameAgentTask(
            service, record, service.context(session_id), ExhaustedClient(),
        )
        task.start()
        task.join(2)

        state = service.requests.public(submitted["request_id"])
        self.assertEqual(state["outcome"], "generation_exhausted")
        self.assertEqual(state["proposal_id"], "")
        self.assertIn("输出上限", state["result"])

    def test_proposal_rejects_unsupported_or_stale_operations(self):
        service = BridgeService()
        session_id = service.handshake(handshake_payload())["session_id"]
        service.update_context({
            "session_id": session_id, "revision": 1,
            "book_revision": "book-revision-a",
            "server_book_revision": "book-revision-a",
            "chapter": {}, "selected_quests": [],
            "book_summary": {"can_edit": True, "server_can_edit": True},
            "registry_summary": {},
        })
        submitted = service.submit_request({
            "session_id": session_id, "context_revision": 1, "prompt": "修改任务",
        })
        record = service.requests.take_next()
        with self.assertRaises(ProtocolError):
            service.requests.create_proposal(record.id, "危险操作", [{
                "kind": "run_command", "command": "stop",
            }])
        proposal = service.requests.create_proposal(record.id, "更新标题", [{
            "kind": "update_quest", "quest_id": "DEF",
            "changes": {"title": "新标题"},
        }])
        service.update_context({
            "session_id": session_id, "revision": 2,
            "book_revision": "book-revision-b",
            "server_book_revision": "book-revision-b",
            "chapter": {}, "selected_quests": [],
            "book_summary": {"can_edit": True, "server_can_edit": True},
            "registry_summary": {},
        })
        with self.assertRaises(ProtocolError):
            service.decide_proposal(proposal["proposal_id"], {
                "session_id": session_id, "context_revision": 2,
            }, confirm=True)
        self.assertEqual(submitted["status"], "queued")

    def test_proposal_requires_edit_permission_and_cancel_invalidates_it(self):
        service = BridgeService()
        session_id = service.handshake(handshake_payload())["session_id"]
        service.update_context({
            "session_id": session_id, "revision": 1,
            "book_revision": "book-revision-a",
            "server_book_revision": "book-revision-a",
            "chapter": {}, "selected_quests": [],
            "book_summary": {"can_edit": False, "server_can_edit": False},
            "registry_summary": {},
        })
        submitted = service.submit_request({
            "session_id": session_id, "context_revision": 1, "prompt": "修改任务",
        })
        record = service.requests.take_next()
        proposal = service.requests.create_proposal(record.id, "更新标题", [{
            "kind": "update_quest", "quest_id": "DEF",
            "changes": {"title": "新标题"},
        }])
        with self.assertRaises(ProtocolError):
            service.decide_proposal(proposal["proposal_id"], {
                "session_id": session_id, "context_revision": 1,
            }, confirm=True)
        service.requests.cancel(submitted["request_id"])
        self.assertEqual(
            service.requests.public_proposal(proposal["proposal_id"])["status"],
            "cancelled",
        )

    def test_shared_project_timeline_survives_new_service(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "bridge.sqlite3")
            first = BridgeService(shared_state=SharedProjectState(path))
            handshake = first.handshake(handshake_payload())
            session_id = handshake["session_id"]
            first.update_context({
                "session_id": session_id, "revision": 1,
                "world_id": "singleplayer:world-a", "chapter": {},
                "selected_quests": [], "book_summary": {}, "registry_summary": {},
            })
            submitted = first.submit_request({
                "session_id": session_id, "context_revision": 1, "prompt": "创建任务",
            })
            record = first.requests.take_next()
            first.requests.complete(record.id, "已完成")
            events = first.events(session_id)
            self.assertEqual([event["kind"] for event in events if event["kind"].startswith("chat.")],
                             ["chat.user", "chat.assistant"])

            second = BridgeService(shared_state=SharedProjectState(path))
            resumed = second.handshake(handshake_payload())
            second.update_context({
                "session_id": resumed["session_id"], "revision": 1,
                "world_id": "singleplayer:world-a", "chapter": {},
                "selected_quests": [], "book_summary": {}, "registry_summary": {},
            })
            self.assertEqual(second.session_identity(resumed["session_id"])["project_id"],
                             first.session_identity(session_id)["project_id"])
            self.assertEqual(len(second.events(resumed["session_id"])), len(events))
            self.assertTrue(submitted["conversation_id"])

    def test_live_snapshot_converts_and_raw_diff_preserves_custom_fields(self):
        envelope = {
            "format": "ftbquests-snbt-v1", "project_id": "project",
            "conversation_id": "conversation", "book_revision": "rev-a",
            "snapshot": {
                "title": "Live", "documents": [
                    {"path": "data.snbt", "snbt": "{version:13,custom_book:1b}"},
                ],
                "chapters": [{
                    "id": "ABC", "filename": "main",
                    "snbt": "{id:\"ABC\",title:\"Main\",custom_chapter:\"keep\",quests:[{id:\"DEF\",title:\"Old\",x:0.0d,y:0.0d,tasks:[{id:\"AAA\",type:\"checkmark\",custom_task:7}],rewards:[]}]}",
                }],
            },
        }
        base = snapshot_to_project_payload(envelope)
        desired = json.loads(json.dumps(base))
        desired["chapters"][0]["quests"][0]["title"] = "New"
        operations = diff_project_payload(base, desired)
        self.assertEqual([value["kind"] for value in operations], ["upsert_quest_raw"])
        self.assertIn("custom_chapter", base["chapters"][0])
        self.assertIn("custom_task", base["chapters"][0]["quests"][0]["tasks"][0])

    def test_game_agent_context_uses_shared_task_book_for_selected_quest_details(self):
        with tempfile.TemporaryDirectory() as root:
            service = BridgeService(shared_state=SharedProjectState(
                os.path.join(root, "bridge.sqlite3"),
            ))
            handshake = service.handshake(handshake_payload())
            session_id = handshake["session_id"]
            service.update_context({
                "session_id": session_id, "revision": 1, "world_id": "world",
                "book_revision": "rev-a", "server_book_revision": "rev-a",
                "chapter": {"id": "ABC", "title": "Boss"},
                "selected_chapters": [{
                    "id": "ABC", "title": "Boss", "quest_ids": ["DEF"],
                }],
                "selected_quests": [{"id": "DEF", "title": "Boss A", "x": 1, "y": 2}],
                "book_summary": {"server_can_edit": True}, "registry_summary": {},
            })
            service.save_book_snapshot({
                "session_id": session_id, "book_revision": "rev-a",
                "format": "ftbquests-snbt-v1",
                "snapshot": {"title": "Live", "documents": [], "chapters": [{
                    "id": "ABC", "filename": "boss",
                    "snbt": (
                        "{id:\"ABC\",title:\"Boss\",quests:[{id:\"DEF\","
                        "title:\"Boss A\",icon:\"minecraft:nether_star\","
                        "rewards:[{id:\"AAA\",type:\"item\",item:\"minecraft:nether_star\"}]}]}"
                    ),
                }]},
            })

            context = service.agent_context(session_id)

            self.assertEqual(context["selected_quest_details_source"],
                             "studio_task_book_snapshot")
            self.assertEqual(context["selected_quest_details"][0]["id"], "DEF")
            self.assertEqual(context["selected_quest_details"][0]["icon"],
                             "minecraft:nether_star")
            self.assertIn("minecraft:nether_star",
                          context["selected_quest_details"][0]["raw_snbt"])
            self.assertEqual(context["selected_chapter_details"][0]["id"], "ABC")
            self.assertNotIn(
                "raw_snbt", context["selected_chapter_details"][0]["quests"][0],
            )
            self.assertEqual(
                context["selected_chapter_details"][0]["quests"][0]["detail_level"],
                "summary",
            )
            self.assertEqual(
                context["selected_chapter_details"][0]["quests"][0]["reward_ids"],
                ["AAA"],
            )

    def test_studio_book_sync_queues_confirmed_transaction(self):
        with tempfile.TemporaryDirectory() as root:
            state_path = os.path.join(root, "bridge.sqlite3")
            service = BridgeService(shared_state=SharedProjectState(state_path))
            handshake = service.handshake(handshake_payload())
            session_id = handshake["session_id"]
            service.update_context({
                "session_id": session_id, "revision": 2, "world_id": "world",
                "book_revision": "rev-a", "server_book_revision": "rev-a",
                "chapter": {}, "selected_quests": [],
                "book_summary": {"server_can_edit": True}, "registry_summary": {},
            })
            service.save_book_snapshot({
                "session_id": session_id, "book_revision": "rev-a",
                "format": "ftbquests-snbt-v1",
                "snapshot": {"title": "Live", "documents": [], "chapters": [{
                    "id": "ABC", "filename": "main",
                    "snbt": "{id:\"ABC\",title:\"Main\",quests:[]}",
                }]},
            })
            desired = service.latest_book_payload()
            desired["chapters"][0]["title"] = "Changed"
            queued = service.queue_studio_book({
                "base_book_revision": "rev-a", "project": desired,
            })
            self.assertEqual(queued["status"], "queued")
            restarted = BridgeService(shared_state=SharedProjectState(state_path))
            resumed = restarted.handshake(handshake_payload())
            restarted.update_context({
                "session_id": resumed["session_id"], "revision": 1, "world_id": "world",
                "book_revision": "rev-a", "server_book_revision": "rev-a",
                "chapter": {}, "selected_quests": [],
                "book_summary": {"server_can_edit": True}, "registry_summary": {},
            })
            transaction = restarted.requests.take_studio_transaction(resumed["session_id"])
            self.assertEqual(transaction["status"], "confirmed")
            self.assertEqual(transaction["operations"][0]["kind"], "upsert_chapter_raw")
            restored_request = restarted.requests.public(transaction["request_id"])
            self.assertEqual(restored_request["outcome"], "proposal_prepared")
