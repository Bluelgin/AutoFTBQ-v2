import unittest

from autoftbq_v2.agent import ProjectAgent
from autoftbq_v2.agent_core.planning import build_run_plan
from autoftbq_v2.ftb_store import FTBQuestStore
from autoftbq_v2.project import ProjectStore, QuestBookProject
from autoftbq_v2.skill_registry import SkillRegistry
from quest_tools import QuestToolbox


class FakeToolClient:
    def chat_with_tools(self, messages, tools, handler, **_kwargs):
        summary = handler("get_project_summary", {})
        self.assert_json(summary)
        skills = handler("list_skills", {})
        self.assert_json_list(skills)
        handler("load_skill", {"skill_id": "plan.mod_branch"})
        chapter = handler("create_chapter", {"title": "机械动力"})
        import json
        chapter_id = json.loads(chapter)["chapter_id"]
        handler("search_items", {"namespace": "create", "query": "press"})
        handler("add_quest", {
            "chapter_id": chapter_id,
            "title": "机械压制",
            "description": "制作机械动力压片机。",
            "task_type": "item",
            "target": "create:mechanical_press",
            "count": 1,
        })
        handler("validate_project", {})
        return "已创建机械动力章节并完成检查。", False

    @staticmethod
    def assert_json(value):
        import json
        assert isinstance(json.loads(value), dict)

    @staticmethod
    def assert_json_list(value):
        import json
        assert isinstance(json.loads(value), list)


class FakeActionClient:
    def __init__(self):
        self.responses = iter([
            ('{"actions":[{"tool":"create_chapter","arguments":{"title":"魔法入门"}}],"reply":"正在创建"}', False),
            ('{"actions":[],"reply":"魔法章节已经创建。"}', False),
        ])

    def chat(self, _messages, **_kwargs):
        return next(self.responses)


class V2AgentTests(unittest.TestCase):
    def test_selected_quest_scope_blocks_writes_to_other_quests(self):
        store = FTBQuestStore.create_new(with_starter=False)
        chapter = store.create_chapter("机械动力")
        selected = store.add_quest(chapter.id, "水车")
        outside = store.add_quest(chapter.id, "冲压机")
        agent = ProjectAgent(store, None)
        agent.set_request_context({
            "intent": "improve",
            "strict": True,
            "chapter_ids": [],
            "quest_ids": [selected.id],
            "creation_chapter_ids": [chapter.id],
        })

        allowed = __import__("json").loads(agent.call_tool("update_quest", {
            "quest_id": selected.id, "title": "水车入门",
        }))
        blocked = __import__("json").loads(agent.call_tool("update_quest", {
            "quest_id": outside.id, "title": "不应修改",
        }))

        self.assertEqual(allowed["title"], "水车入门")
        self.assertIn("不在用户选择", blocked["error"])
        self.assertEqual(store.quest(outside.id)[1].title, "冲压机")
        self.assertFalse(agent._transaction_failure)

    def test_inspect_mode_is_enforced_as_read_only(self):
        store = FTBQuestStore.create_new(with_starter=False)
        chapter = store.create_chapter("原章节")
        agent = ProjectAgent(store, None)
        agent.set_request_context({"intent": "inspect", "strict": False})

        result = __import__("json").loads(agent.call_tool("create_chapter", {"title": "越界章节"}))

        self.assertIn("只读", result["error"])
        self.assertEqual([value.title for value in store.project.chapters], [chapter.title])
        self.assertFalse(agent._transaction_failure)

    def test_polish_mode_rejects_non_text_field_changes(self):
        store = FTBQuestStore.create_new(with_starter=False)
        chapter = store.create_chapter("机械动力")
        quest = store.add_quest(chapter.id, "水车")
        agent = ProjectAgent(store, None)
        agent.set_request_context({
            "intent": "polish", "strict": True,
            "chapter_ids": [], "quest_ids": [quest.id],
        })

        result = __import__("json").loads(agent.call_tool("update_quest_fields", {
            "quest_id": quest.id, "changes": {"x": 8},
        }))

        self.assertIn("只能修改标题", result["error"])

    def test_strict_scope_classifies_every_mutating_tool(self):
        store = FTBQuestStore.create_new(with_starter=False)
        chapter = store.create_chapter("机械动力")
        quest = store.add_quest(chapter.id, "水车")
        agent = ProjectAgent(store, None)
        agent.set_request_context({
            "intent": "improve", "strict": True,
            "chapter_ids": [], "quest_ids": [quest.id],
            "creation_chapter_ids": [chapter.id],
        })

        unrestricted = [
            spec["function"]["name"]
            for spec in agent.tool_specs()
            if spec["function"]["name"] not in agent.READ_ONLY_TOOLS
            and not agent._scope_violation(spec["function"]["name"], {})
        ]

        self.assertEqual(unrestricted, [])

    def test_plan_does_not_treat_existing_quest_count_as_new_work(self):
        plan = build_run_plan("把现有10个任务连接成主线", FTBQuestStore.create_new(with_starter=False))

        self.assertNotIn("quests_added", {criterion.kind for criterion in plan.criteria})
        self.assertIn("dependencies_added", {criterion.kind for criterion in plan.criteria})

    def test_plan_tracks_explicit_task_type_and_count(self):
        plan = build_run_plan("创建6个手动勾选任务并连线，4个后换到下一层", FTBQuestStore.create_new(with_starter=False))
        typed = next(criterion for criterion in plan.criteria if criterion.kind == "new_quests_typed")
        row_wrap = next(criterion for criterion in plan.criteria if criterion.kind == "row_wrap")

        self.assertEqual((typed.value, typed.target), ("checkmark", 6))
        self.assertEqual(row_wrap.target, 4)

    def test_plan_treats_all_gameplay_chapter_as_substantial_work(self):
        plan = build_run_plan(
            "建议一个章节，内容包含全部机械动力玩法，由入门到精通，太长就换到下一行",
            FTBQuestStore.create_new(with_starter=False),
        )
        criteria = {criterion.kind: criterion for criterion in plan.criteria}

        self.assertEqual(criteria["quests_added"].target, 8)
        self.assertEqual(criteria["dependencies_added"].target, 7)
        self.assertEqual(criteria["row_wrap"].target, 5)
        self.assertIn("chapters_added", criteria)

    def test_relevant_skills_are_matched_without_model_tool_calls(self):
        matches = SkillRegistry().match("创建主线流程，往下一层排列并连线")
        skill_ids = {match["skill_id"] for match in matches}

        self.assertEqual(skill_ids, {"plan.mainline", "layout.dependencies"})

    def test_add_quest_chain_creates_dependencies_and_wraps_layout(self):
        store = FTBQuestStore.create_new(with_starter=False)
        chapter = store.create_chapter("机械动力")
        agent = ProjectAgent(store, None)
        result = __import__("json").loads(agent.call_tool("add_quest_chain", {
            "chapter_id": chapter.id,
            "row_width": 4,
            "quests": [
                {"title": f"主线 {index + 1}", "task_type": "checkmark"}
                for index in range(7)
            ],
        }))

        quests = store.chapter(chapter.id).quests
        self.assertEqual(len(result["created"]), 7)
        self.assertEqual(quests[0].dependencies, [])
        for index in range(1, len(quests)):
            self.assertEqual(quests[index].dependencies, [quests[index - 1].id])
        self.assertGreater(quests[4].y, quests[3].y)
        self.assertFalse(any(issue["severity"] == "error" for issue in store.validate()))

    def test_dependency_plan_supports_one_prerequisite_for_two_quests(self):
        store = FTBQuestStore.create_new(with_starter=False)
        chapter = store.create_chapter("分支")
        source = store.add_quest(chapter.id, "共同前置")
        left = store.add_quest(chapter.id, "左支线")
        right = store.add_quest(chapter.id, "右支线")
        agent = ProjectAgent(store, None)

        result = __import__("json").loads(agent.call_tool("apply_dependency_plan", {
            "edges": [
                {"quest_id": left.id, "dependency_id": source.id},
                {"quest_id": right.id, "dependency_id": source.id},
            ],
        }))

        self.assertEqual(len(result["applied"]), 2)
        self.assertEqual(left.dependencies, [source.id])
        self.assertEqual(right.dependencies, [source.id])

    def test_dependency_plan_rolls_back_all_edges_when_one_is_invalid(self):
        store = FTBQuestStore.create_new(with_starter=False)
        chapter = store.create_chapter("回滚")
        first = store.add_quest(chapter.id, "任务一")
        second = store.add_quest(chapter.id, "任务二")
        agent = ProjectAgent(store, None)

        with self.assertRaises(ValueError):
            agent.call_tool("apply_dependency_plan", {
                "edges": [
                    {"quest_id": second.id, "dependency_id": first.id},
                    {"quest_id": first.id, "dependency_id": "missing"},
                ],
            })

        _chapter, restored_second = store.quest(second.id)
        self.assertEqual(restored_second.dependencies, [])

    def test_agent_allows_enough_tool_rounds_for_complete_quest_workflows(self):
        class RoundCaptureClient:
            def __init__(self):
                self.max_rounds = 0

            def chat_with_tools(self, _messages, _tools, _handler, **kwargs):
                self.max_rounds = kwargs.get("max_rounds", 0)
                return "已检查，没有修改"

        client = RoundCaptureClient()
        agent = ProjectAgent(ProjectStore(QuestBookProject()), client)

        agent.run("检查任务书")

        self.assertGreaterEqual(client.max_rounds, 12)

    def test_basic_project_supports_cross_chapter_dependencies(self):
        store = ProjectStore(QuestBookProject())
        first = store.create_chapter("主线")
        second = store.create_chapter("支线")
        source = store.add_quest(first.id, "前置")
        target = store.add_quest(second.id, "后续")

        store.connect(target.id, source.id)

        self.assertEqual(target.dependencies, [source.id])
        self.assertFalse(any(issue["severity"] == "error" for issue in store.validate()))

    def test_agent_changes_project_only_through_tools(self):
        store = ProjectStore(QuestBookProject())
        toolbox = QuestToolbox({"create": {"create:mechanical_press": "Mechanical Press"}})
        actions = []
        agent = ProjectAgent(store, FakeToolClient(), toolbox, lambda name, *_: actions.append(name))

        reply = agent.run("创建机械动力任务")

        self.assertIn("完成检查", reply)
        self.assertEqual(store.project.chapters[0].title, "机械动力")
        self.assertEqual(store.project.chapters[0].quests[0].tasks[0].target, "create:mechanical_press")
        self.assertEqual(actions, [
            "agent_plan", "get_project_summary", "list_skills", "load_skill", "create_chapter",
            "agent_checkpoint", "search_items", "add_quest", "agent_checkpoint",
            "validate_project", "agent_verify",
        ])
        self.assertTrue(agent.has_pending_changes)
        self.assertTrue(agent.commit_transaction())

    def test_plain_chat_client_uses_bounded_action_protocol(self):
        store = ProjectStore(QuestBookProject())
        agent = ProjectAgent(store, FakeActionClient())

        reply = agent.run("创建魔法章节")

        self.assertEqual(reply, "魔法章节已经创建。")
        self.assertEqual(store.project.chapters[0].title, "魔法入门")
        self.assertTrue(agent.rollback_transaction())
        self.assertEqual(store.project.chapters, [])

    def test_failed_mutation_keeps_the_previous_safe_checkpoint(self):
        store = ProjectStore(QuestBookProject())
        agent = ProjectAgent(store, None)
        agent._begin_transaction()

        agent.call_tool("create_chapter", {"title": "应当保留"})
        result = __import__("json").loads(agent.call_tool(
            "add_quest", {"chapter_id": "missing", "title": "失败", "task_type": "checkmark"},
        ))

        self.assertIn("error", result)
        self.assertEqual([chapter.title for chapter in store.project.chapters], ["应当保留"])
        self.assertEqual(agent.checkpoint_count, 1)
        self.assertTrue(agent.has_pending_changes)
        self.assertFalse(agent._transaction_failure)

    def test_new_validation_error_rejects_only_the_invalid_tool(self):
        store = ProjectStore(QuestBookProject())
        agent = ProjectAgent(store, None)
        agent._begin_transaction()
        chapter_id = __import__("json").loads(
            agent.call_tool("create_chapter", {"title": "安全章节"})
        )["chapter_id"]
        quest_id = __import__("json").loads(agent.call_tool("add_quest", {
            "chapter_id": chapter_id, "title": "安全任务", "task_type": "checkmark",
        }))["quest_id"]

        result = __import__("json").loads(agent.call_tool(
            "update_quest", {"quest_id": quest_id, "task_type": "item", "target": "missing_namespace"},
        ))

        self.assertIn("error", result)
        self.assertEqual(store.quest(quest_id)[1].tasks[0].type, "checkmark")
        self.assertEqual(agent.checkpoint_count, 2)
        self.assertFalse(any(issue["severity"] == "error" for issue in store.validate()))

    def test_last_checkpoint_undo_preserves_earlier_agent_work(self):
        store = ProjectStore(QuestBookProject())
        agent = ProjectAgent(store, None)
        agent._begin_transaction()
        chapter_id = __import__("json").loads(
            agent.call_tool("create_chapter", {"title": "Boss 挑战"})
        )["chapter_id"]
        agent.call_tool("add_quest", {
            "chapter_id": chapter_id, "title": "末影龙", "task_type": "checkmark",
        })

        self.assertTrue(agent.rollback_last_checkpoint())

        self.assertEqual([chapter.title for chapter in store.project.chapters], ["Boss 挑战"])
        self.assertEqual(store.project.chapters[0].quests, [])
        self.assertEqual(agent.checkpoint_count, 1)

    def test_network_interruption_retains_latest_safe_checkpoint(self):
        class InterruptedClient:
            def chat_with_tools(self, _messages, _tools, handler, **_kwargs):
                handler("create_chapter", {"title": "断线前已完成"})
                raise ConnectionError("temporary disconnect")

        store = ProjectStore(QuestBookProject())
        agent = ProjectAgent(store, InterruptedClient())

        with self.assertRaises(ConnectionError):
            agent.run("创建章节")

        self.assertEqual([chapter.title for chapter in store.project.chapters], ["断线前已完成"])
        self.assertTrue(agent.has_pending_changes)
        self.assertEqual(agent.checkpoint_count, 1)

    def test_continuation_reuses_existing_checkpoint_transaction(self):
        store = ProjectStore(QuestBookProject())
        agent = ProjectAgent(store, None)
        agent._begin_transaction()
        agent.call_tool("create_chapter", {"title": "已完成阶段"})

        agent._begin_transaction(resume=True)

        self.assertEqual([chapter.title for chapter in store.project.chapters], ["已完成阶段"])
        self.assertEqual(agent.checkpoint_count, 1)
        self.assertTrue(agent.has_pending_changes)

    def test_checkpoint_history_is_bounded_but_full_rollback_remains_available(self):
        store = ProjectStore(QuestBookProject())
        agent = ProjectAgent(store, None)
        agent._begin_transaction()
        for index in range(agent.MAX_CHECKPOINTS + 5):
            agent.call_tool("create_chapter", {"title": f"阶段 {index + 1}"})

        self.assertEqual(agent.checkpoint_count, agent.MAX_CHECKPOINTS)
        self.assertEqual(len(store.project.chapters), agent.MAX_CHECKPOINTS + 5)
        self.assertTrue(agent.rollback_transaction())
        self.assertEqual(store.project.chapters, [])

    def test_tool_client_may_return_plain_text_instead_of_tuple(self):
        class TextClient:
            def chat_with_tools(self, _messages, _tools, _handler, **_kwargs):
                return "没有需要修改的内容"

        agent = ProjectAgent(ProjectStore(QuestBookProject()), TextClient())
        self.assertEqual(agent.run("查看一下"), "没有需要修改的内容")

    def test_agent_can_search_registry_and_add_typed_condition(self):
        from autoftbq_v2.ftb_store import FTBQuestStore

        store = FTBQuestStore.create_new()
        quest = store.project.chapters[0].quests[0]
        agent = ProjectAgent(store, None)

        matches = __import__("json").loads(agent.call_tool(
            "search_registry", {"registry": "entity", "query": "凋灵"},
        ))
        added = __import__("json").loads(agent.call_tool(
            "add_task_condition", {
                "quest_id": quest.id, "type_id": "kill",
                "values": {"entity": "minecraft:wither", "value": 1},
            },
        ))

        self.assertTrue(any(value["id"] == "minecraft:wither" for value in matches))
        self.assertEqual(added["type"], "kill")
        self.assertEqual(store.raw_sections(quest.id)[0][-1]["entity"], "minecraft:wither")

    def test_agent_automatically_repairs_missing_quests_and_dependencies(self):
        class RepairingClient:
            def __init__(self):
                self.calls = 0
                self.chapter_id = ""
                self.quest_ids = []

            def chat_with_tools(self, _messages, _tools, handler, **_kwargs):
                import json
                self.calls += 1
                if self.calls == 1:
                    self.chapter_id = json.loads(handler("create_chapter", {"title": "机械动力主线"}))["chapter_id"]
                    for title in ("动力起步", "传动基础"):
                        self.quest_ids.append(json.loads(handler("add_quest", {
                            "chapter_id": self.chapter_id, "title": title, "task_type": "checkmark",
                        }))["quest_id"])
                    return "已经创建两个任务", False
                handler("apply_dependency_plan", {"edges": [{
                    "quest_id": self.quest_ids[1], "dependency_id": self.quest_ids[0],
                }]})
                result = json.loads(handler("add_quest_chain", {
                    "chapter_id": self.chapter_id,
                    "start_dependency_id": self.quest_ids[1],
                    "quests": [
                        {"title": "自动化入门", "task_type": "checkmark"},
                        {"title": "进阶工厂", "task_type": "checkmark"},
                    ],
                }))
                self.quest_ids.extend(value["quest_id"] for value in result["created"])
                handler("validate_project", {})
                return "已经补齐任务和连线", False

        store = FTBQuestStore.create_new(with_starter=False)
        client = RepairingClient()
        agent = ProjectAgent(store, client)

        reply = agent.run("创建一个完整的机械动力主线章节，由入门到进阶")

        quests = store.project.chapters[0].quests
        self.assertEqual(client.calls, 2)
        self.assertEqual(len(quests), 4)
        self.assertEqual(sum(len(quest.dependencies) for quest in quests), 3)
        self.assertEqual(agent.run_plan.phase, "completed")
        self.assertEqual(reply, "已经补齐任务和连线")

    def test_agent_does_not_claim_completion_when_repair_still_fails(self):
        class IncompleteClient:
            def __init__(self):
                self.calls = 0

            def chat_with_tools(self, _messages, _tools, handler, **_kwargs):
                import json
                self.calls += 1
                if self.calls == 1:
                    chapter_id = json.loads(handler("create_chapter", {"title": "未完成主线"}))["chapter_id"]
                    handler("add_quest", {"chapter_id": chapter_id, "title": "任务一", "task_type": "checkmark"})
                    handler("add_quest", {"chapter_id": chapter_id, "title": "任务二", "task_type": "checkmark"})
                return "全部完成", False

        agent = ProjectAgent(FTBQuestStore.create_new(with_starter=False), IncompleteClient())

        reply = agent.run("创建完整主线章节")

        self.assertIn("没有冒充完成", reply)
        self.assertIn("发送“继续”", reply)
        self.assertEqual(agent.run_plan.phase, "needs_attention")
        self.assertTrue(agent.run_plan.failures)

    def test_hallucinated_unknown_tool_does_not_poison_valid_later_edits(self):
        class RecoveringClient:
            def chat_with_tools(self, _messages, _tools, handler, **_kwargs):
                import json
                unknown = json.loads(handler("read_file", {"path": "data.snbt"}))
                self.unknown_error = unknown["error"]
                chapter_id = json.loads(handler("create_chapter", {"title": "可靠主线"}))["chapter_id"]
                handler("add_quest_chain", {
                    "chapter_id": chapter_id,
                    "quests": [
                        {"title": f"任务 {index + 1}", "task_type": "checkmark"}
                        for index in range(4)
                    ],
                })
                return "已改用现有工具完成", False

        client = RecoveringClient()
        store = FTBQuestStore.create_new(with_starter=False)
        agent = ProjectAgent(store, client)

        reply = agent.run("创建一个完整主线章节")

        self.assertIn("read_file", client.unknown_error)
        self.assertEqual(reply, "已改用现有工具完成")
        self.assertEqual(len(store.project.chapters[0].quests), 4)
        self.assertEqual(agent.run_plan.phase, "completed")

    def test_item_search_budget_returns_recoverable_error(self):
        agent = ProjectAgent(FTBQuestStore.create_new(with_starter=False), None)

        for _index in range(6):
            result = __import__("json").loads(agent.call_tool("search_items", {"query": "gear"}))
            self.assertIsInstance(result, list)
        limited = __import__("json").loads(agent.call_tool("search_items", {"query": "shaft"}))

        self.assertIn("6 次上限", limited["error"])
        self.assertIn("已有搜索结果", limited["recovery"])

    def test_incomplete_plan_can_be_restored_and_continued(self):
        first = ProjectAgent(FTBQuestStore.create_new(with_starter=False), None)
        plan = first.prepare_run("创建6个任务并连线")
        plan.phase = "needs_attention"
        plan.failures = ["任务不足"]

        restored = ProjectAgent(first.store, None)
        restored.import_run_state(first.export_run_state())
        resumed = restored.prepare_run("继续")

        self.assertEqual(resumed.request, "创建6个任务并连线")
        self.assertEqual(resumed.failures, ["任务不足"])


if __name__ == "__main__":
    unittest.main()
