import unittest

from autoftbq_v2.editor.session import EditorSessionState
from autoftbq_v2.project import Chapter, ProjectStore, Quest, QuestBookProject


class EditorSessionStateTests(unittest.TestCase):
    def setUp(self):
        self.first = Chapter(id="chapter_a", title="A", quests=[Quest(id="quest_a"), Quest(id="quest_b")])
        self.second = Chapter(id="chapter_b", title="B", quests=[Quest(id="quest_c")])
        self.store = ProjectStore(QuestBookProject(chapters=[self.first, self.second]))

    def test_reconcile_repairs_stale_selection_and_context(self):
        state = EditorSessionState("missing", "missing", {"chapter_a", "gone"}, {"quest_c", "gone"})

        self.assertEqual(state.reconcile_selection(self.store), ("chapter_a", "quest_a"))
        self.assertEqual(state.agent_chapter_ids, {"chapter_a"})
        self.assertEqual(state.agent_quest_ids, {"quest_c"})

    def test_chapter_and_quest_context_are_mutually_exclusive(self):
        state = EditorSessionState()
        self.assertTrue(state.toggle_agent_quest(self.store, "quest_a"))
        self.assertTrue(state.toggle_agent_chapter(self.store, "chapter_a"))

        self.assertEqual(state.agent_chapter_ids, {"chapter_a"})
        self.assertEqual(state.agent_quest_ids, set())

    def test_selecting_quest_updates_its_chapter(self):
        state = EditorSessionState()
        self.assertTrue(state.select_quest(self.store, "quest_c"))
        self.assertEqual((state.current_chapter_id, state.current_quest_id), ("chapter_b", "quest_c"))


if __name__ == "__main__":
    unittest.main()
