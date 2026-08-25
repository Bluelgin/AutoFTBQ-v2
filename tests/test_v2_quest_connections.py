import unittest

from autoftbq_v2.ftb_store import FTBQuestStore
from autoftbq_v2.editor.quest_connections import QuestConnectionController


class QuestConnectionControllerTests(unittest.TestCase):
    def setUp(self):
        self.store = FTBQuestStore.create_new(with_starter=False)
        chapter = self.store.create_chapter("连接测试")
        self.first = self.store.add_quest(chapter.id, "第一步")
        self.second = self.store.add_quest(chapter.id, "第二步")
        self.third = self.store.add_quest(chapter.id, "第三步")
        self.controller = QuestConnectionController(lambda: self.store)

    def connect(self, source, target):
        selected = self.controller.click(source.id)
        result = self.controller.click(target.id)
        self.assertEqual(selected.status, "selected")
        return result

    def test_two_clicks_create_dependency(self):
        result = self.connect(self.first, self.second)

        self.assertTrue(result.connected)
        self.assertEqual(result.source_id, self.first.id)
        self.assertEqual(self.store.quest(self.second.id)[1].dependencies, [self.first.id])
        self.assertEqual(self.controller.source_id, "")

    def test_one_prerequisite_can_feed_multiple_targets(self):
        self.connect(self.first, self.second)
        self.connect(self.first, self.third)

        self.assertEqual(self.store.quest(self.second.id)[1].dependencies, [self.first.id])
        self.assertEqual(self.store.quest(self.third.id)[1].dependencies, [self.first.id])

    def test_duplicate_and_cycle_are_rejected_without_mutation(self):
        self.connect(self.first, self.second)

        duplicate = self.connect(self.first, self.second)
        cycle = self.connect(self.second, self.first)

        self.assertIn("已经连接", duplicate.message)
        self.assertIn("循环依赖", cycle.message)
        self.assertEqual(self.store.quest(self.first.id)[1].dependencies, [])

    def test_reset_discards_pending_source(self):
        self.controller.click(self.first.id)

        self.controller.reset()

        self.assertEqual(self.controller.source_id, "")


if __name__ == "__main__":
    unittest.main()
