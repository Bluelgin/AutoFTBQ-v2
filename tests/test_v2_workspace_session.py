import os
import tempfile
import unittest

from autoftbq_v2.ftb_store import FTBQuestStore
from autoftbq_v2.infrastructure.workspace_session import WorkspaceSessionRepository


class WorkspaceSessionRepositoryTests(unittest.TestCase):
    def test_round_trips_project_and_session_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            repository = WorkspaceSessionRepository(root)
            store = FTBQuestStore.create_new("未保存草稿")
            session = {
                "format": "autoftbq-v2-session",
                "format_version": 1,
                "prompt": "继续完善",
            }

            repository.save(store, session)
            loaded = repository.load()

            self.assertTrue(repository.exists())
            self.assertEqual(loaded.store.project.title, "未保存草稿")
            self.assertEqual(loaded.session["prompt"], "继续完善")
            self.assertFalse(os.path.exists(repository.session_path + ".tmp"))

    def test_rejects_invalid_session_format(self):
        with tempfile.TemporaryDirectory() as root:
            repository = WorkspaceSessionRepository(root)
            with self.assertRaises(ValueError):
                repository.save(FTBQuestStore.create_new(), {"format": "wrong"})


if __name__ == "__main__":
    unittest.main()
