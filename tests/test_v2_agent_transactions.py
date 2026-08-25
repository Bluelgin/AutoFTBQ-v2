import unittest

from autoftbq_v2.agent import ProjectAgent
from autoftbq_v2.agent_core.transactions import AgentTransactionManager
from autoftbq_v2.project import Chapter, ProjectStore, QuestBookProject


class CountingProjectStore(ProjectStore):
    def __init__(self):
        super().__init__(QuestBookProject())
        self.full_captures = 0
        self.step_captures = 0

    def capture_state(self):
        self.full_captures += 1
        return super().capture_state()

    def capture_checkpoint_state(self):
        self.step_captures += 1
        return super().capture_checkpoint_state()


class AgentTransactionManagerTests(unittest.TestCase):
    def test_agent_writes_use_lightweight_step_snapshots(self):
        store = CountingProjectStore()
        agent = ProjectAgent(store, None)

        agent._begin_transaction()
        agent.call_tool("create_chapter", {"title": "机械动力"})

        self.assertEqual(store.full_captures, 1)
        self.assertEqual(store.step_captures, 3)
        self.assertEqual(agent.checkpoint_count, 1)

    def test_manager_can_undo_one_step_and_then_the_complete_run(self):
        store = ProjectStore(QuestBookProject())
        manager = AgentTransactionManager(store)
        manager.begin(set())
        store.project.chapters.append(Chapter(title="第一步"))
        manager.accept_tool("create_chapter", set())
        store.project.chapters.append(Chapter(title="第二步"))
        manager.accept_tool("create_chapter", set())

        self.assertTrue(manager.rollback_last())
        self.assertEqual([chapter.title for chapter in store.project.chapters], ["第一步"])
        self.assertTrue(manager.rollback_all())
        self.assertEqual(store.project.chapters, [])


if __name__ == "__main__":
    unittest.main()
