import os
import tempfile
import unittest

from snbt_parser import to_snbt

from autoftbq_v2.ftb.source import FTBBookSourceReader, locate_quest_root


class FTBBookSourceReaderTests(unittest.TestCase):
    def test_reads_chapters_supporting_documents_and_collects_bad_files(self):
        with tempfile.TemporaryDirectory() as pack:
            root = os.path.join(pack, "config", "ftbquests", "quests")
            os.makedirs(os.path.join(root, "chapters"))
            with open(os.path.join(root, "chapters", "good.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt({"id": "chapter", "quests": []}))
            with open(os.path.join(root, "chapters", "bad.snbt"), "w", encoding="utf-8") as handle:
                handle.write("[")
            with open(os.path.join(root, "data.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt({"version": 13}))

            source = FTBBookSourceReader().read(root)

            self.assertEqual(locate_quest_root(pack), root)
            self.assertEqual(source.chapters[0][0], "good.snbt")
            self.assertEqual(source.documents["data.snbt"]["version"], 13)
            self.assertTrue(any("bad.snbt" in error for error in source.errors))

    def test_rejects_directory_without_chapters(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                FTBBookSourceReader().read(root)


if __name__ == "__main__":
    unittest.main()
