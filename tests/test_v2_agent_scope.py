import unittest

from autoftbq_v2.agent_core.scope import AgentScopePolicy
from autoftbq_v2.ftb_store import FTBQuestStore


class AgentScopePolicyTests(unittest.TestCase):
    def setUp(self):
        self.store = FTBQuestStore.create_new(with_starter=False)
        self.chapter = self.store.create_chapter("机械动力")
        self.selected = self.store.add_quest(self.chapter.id, "水车")
        self.outside = self.store.add_quest(self.chapter.id, "冲压机")
        self.policy = AgentScopePolicy(self.store, {"get_project_summary"})

    def test_read_only_tool_is_always_allowed(self):
        violation = self.policy.violation(
            "get_project_summary", {}, {"intent": "inspect", "strict": True},
        )

        self.assertEqual(violation, "")

    def test_selected_quest_scope_blocks_an_unselected_sibling(self):
        scope = {
            "intent": "improve",
            "strict": True,
            "chapter_ids": [],
            "quest_ids": [self.selected.id],
            "creation_chapter_ids": [self.chapter.id],
        }

        self.assertEqual(
            self.policy.violation(
                "update_quest", {"quest_id": self.selected.id, "title": "新标题"}, scope,
            ),
            "",
        )
        self.assertIn(
            "不在用户选择",
            self.policy.violation(
                "update_quest", {"quest_id": self.outside.id, "title": "越界"}, scope,
            ),
        )

    def test_chapter_scope_allows_quests_in_that_chapter(self):
        scope = {
            "intent": "improve",
            "strict": True,
            "chapter_ids": [self.chapter.id],
            "quest_ids": [],
        }

        self.assertEqual(
            self.policy.violation(
                "remove_quest", {"quest_id": self.outside.id}, scope,
            ),
            "",
        )

    def test_polish_mode_rejects_layout_fields_before_scope_check(self):
        violation = self.policy.violation(
            "update_quest_fields",
            {"quest_id": self.selected.id, "changes": {"x": 4}},
            {"intent": "polish", "strict": False},
        )

        self.assertIn("只能修改标题", violation)


if __name__ == "__main__":
    unittest.main()
