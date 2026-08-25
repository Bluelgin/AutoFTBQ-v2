import unittest

from autoftbq_v2.agent_core.messages import AgentMessageBuilder


class AgentMessageBuilderTests(unittest.TestCase):
    def test_build_keeps_only_recent_history_and_structured_context(self):
        builder = AgentMessageBuilder("system")
        history = [{"role": "user", "content": str(index)} for index in range(12)]

        messages = builder.build(
            history=history,
            project_summary={"chapters": 2},
            skill_catalog=[{"id": "layout"}],
            matched_skills=[{"id": "layout"}],
            request_context={"intent": "layout"},
            plan_instructions="先检查再移动",
            request="整理布局",
        )

        self.assertEqual(messages[0], {"role": "system", "content": "system"})
        self.assertEqual(messages[1]["content"], "2")
        self.assertEqual(messages[-2]["content"], "11")
        self.assertIn('"intent": "layout"', messages[-1]["content"])
        self.assertIn("用户要求：整理布局", messages[-1]["content"])

    def test_repair_message_lists_each_failed_criterion(self):
        messages = AgentMessageBuilder.build_repair(
            [{"role": "system", "content": "system"}],
            "已完成一部分",
            ["还缺连线", "任务数量不足"],
        )

        self.assertEqual(messages[-2]["role"], "assistant")
        self.assertIn("- 还缺连线", messages[-1]["content"])
        self.assertIn("- 任务数量不足", messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
