import unittest

from autoftbq_v2.project import Chapter, ProjectStore, Quest, QuestBookProject, Task
from autoftbq_v2.editor.quest_inspector import condition_summary, inspector_data, parse_sections


class QuestInspectorTests(unittest.TestCase):
    def test_builds_view_data_without_qt_widgets(self):
        quest = Quest(
            id="quest", title="水车", subtitle="动力起点", icon="create:water_wheel",
            description=["第一行", "第二行"], tasks=[Task("item", "create:water_wheel", 2)],
        )
        store = ProjectStore(QuestBookProject(chapters=[Chapter(id="chapter", quests=[quest])]))

        data = inspector_data(store, quest)

        self.assertEqual(data.chapter_id, "chapter")
        self.assertEqual(data.task_type, "item")
        self.assertEqual(data.target, "create:water_wheel")
        self.assertEqual(data.description, "第一行\n第二行")
        self.assertIn("create:water_wheel", data.tasks_snbt)

    def test_condition_summary_caps_visible_entries(self):
        quest = Quest(tasks=[Task("item", "a"), Task("kill", "b"), Task("dimension", "c"), Task("checkmark")])
        summary = condition_summary(quest)

        self.assertIn("共 4 条", summary)
        self.assertIn("另有 1 条", summary)

    def test_raw_sections_share_one_parser_boundary(self):
        tasks, rewards = parse_sections('[{type:"checkmark"}]', "[]")
        self.assertEqual(tasks[0]["type"], "checkmark")
        self.assertEqual(rewards, [])


if __name__ == "__main__":
    unittest.main()
