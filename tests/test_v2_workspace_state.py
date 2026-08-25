import unittest

from autoftbq_v2.ftb_store import FTBQuestStore
from autoftbq_v2.infrastructure.workspace_state import WorkspaceState


class WorkspaceStateTests(unittest.TestCase):
    def test_normalizes_untrusted_session_lists_and_context(self):
        store = FTBQuestStore.create_new(with_starter=False)
        store.project.mod_folder = "pack-folder"
        session = {
            "chat": [{"role": "user", "text": index} for index in range(305)],
            "actions": [{"name": "move", "detail": index} for index in range(505)],
            "agent_history": [
                {"role": "system", "content": "drop"},
                *({"role": "user", "content": str(index)} for index in range(22)),
            ],
            "agent_queue": ["", " 继续 "],
            "agent_context": {"chapter_ids": [1], "quest_ids": [2]},
        }

        state = WorkspaceState.from_dict(session, store)

        self.assertEqual(len(state.chat), 300)
        self.assertEqual(len(state.actions), 500)
        self.assertEqual(len(state.agent_history), 20)
        self.assertEqual(state.agent_queue, ["继续"])
        self.assertEqual(state.agent_chapter_ids, {"1"})
        self.assertEqual(state.last_modpack_folder, "pack-folder")

    def test_round_trip_preserves_editor_and_agent_state(self):
        store = FTBQuestStore.create_new(with_starter=False)
        original = WorkspaceState(
            project_path="book.json",
            current_chapter_id="chapter",
            current_quest_id="quest",
            agent_run_state={"phase": "repairing"},
            agent_request_context={"intent": "improve"},
            agent_queue=["继续"],
            agent_chapter_ids={"chapter"},
            prompt="优化主线",
            view={"zoom": 1.5, "scroll_x": 20},
        )

        restored = WorkspaceState.from_dict(original.to_dict(), store)

        self.assertEqual(restored.project_path, "book.json")
        self.assertEqual(restored.agent_run_state["phase"], "repairing")
        self.assertEqual(restored.agent_chapter_ids, {"chapter"})
        self.assertEqual(restored.view["zoom"], 1.5)


if __name__ == "__main__":
    unittest.main()
