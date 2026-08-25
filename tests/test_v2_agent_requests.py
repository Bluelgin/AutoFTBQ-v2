import unittest

from autoftbq_v2.agent_core.requests import parse_request, prepare_request, structured_prompt
from autoftbq_v2.project import Chapter, ProjectStore, Quest, QuestBookProject


class AgentRequestTests(unittest.TestCase):
    def test_slash_command_has_priority_over_instruction_words(self):
        parsed = parse_request("/检查 修复这个章节的问题")

        self.assertEqual(parsed.intent, "inspect")
        self.assertEqual(parsed.command, "/检查")
        self.assertEqual(parsed.instruction, "修复这个章节的问题")

    def test_natural_language_detects_specific_intents_before_generic_improvement(self):
        self.assertEqual(parse_request("优化一下任务布局").intent, "layout")
        self.assertEqual(parse_request("帮我修复前置关系").intent, "connect")
        self.assertEqual(parse_request("润色这些任务描述").intent, "polish")

    def test_structured_prompt_carries_scope_and_permissions(self):
        parsed = parse_request("/改进 优化描述")
        prompt = structured_prompt(parsed, {
            "strict": True,
            "chapter_labels": [],
            "quest_labels": ["水车", "动力冲压机"],
        })

        self.assertIn("执行模式：改进", prompt)
        self.assertIn("任务：水车、动力冲压机", prompt)
        self.assertIn("只能修改上述明确作用域", prompt)

    def test_prepare_request_resolves_selected_quest_scope(self):
        chapter = Chapter(id="chapter", title="机械动力", quests=[Quest(id="water_wheel", title="水车")])
        store = ProjectStore(QuestBookProject(chapters=[chapter]))

        prompt, scope, error = prepare_request(
            "/改进 优化这个任务", store, selected_quest_ids={"water_wheel"},
        )

        self.assertFalse(error)
        self.assertIn("任务：水车", prompt)
        self.assertEqual(scope["quest_ids"], ["water_wheel"])
        self.assertEqual(scope["creation_chapter_ids"], ["chapter"])

    def test_prepare_request_rejects_connect_without_two_targets(self):
        store = ProjectStore(QuestBookProject())
        prompt, scope, error = prepare_request("/连线 修复前置", store)

        self.assertIsNone(prompt)
        self.assertIsNone(scope)
        self.assertIn("需要明确范围", error)


if __name__ == "__main__":
    unittest.main()
