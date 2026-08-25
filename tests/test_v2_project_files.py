import os
import tempfile
import unittest

from autoftbq_v2.ftb_store import FTBQuestStore
from autoftbq_v2.infrastructure.project_files import ProjectFileService


class ProjectFileServiceTests(unittest.TestCase):
    def test_draft_round_trip_uses_existing_store_format(self):
        service = ProjectFileService()
        store = FTBQuestStore.create_new(with_starter=False)
        chapter = store.create_chapter("测试章节")
        store.add_quest(chapter.id, "测试任务")

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "book.autoftbq.json")
            result = service.save(store, path)
            loaded = service.load(path)

        self.assertEqual(result, {"kind": "draft", "path": path})
        self.assertEqual(loaded.project.chapters[0].title, "测试章节")
        self.assertEqual(loaded.project.chapters[0].quests[0].title, "测试任务")

    def test_draft_save_requires_a_path(self):
        service = ProjectFileService()
        store = FTBQuestStore.create_new(with_starter=False)

        with self.assertRaisesRegex(ValueError, "文件路径"):
            service.save(store)

    def test_real_store_save_keeps_native_save_all_result(self):
        class FakeRealStore:
            is_real = True

            @staticmethod
            def save_all():
                return {"saved": 3, "backup": "backup-path"}

        result = ProjectFileService().save(FakeRealStore())

        self.assertEqual(result["kind"], "real")
        self.assertEqual(result["saved"], 3)
        self.assertEqual(result["backup"], "backup-path")


if __name__ == "__main__":
    unittest.main()
