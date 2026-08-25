import os
import tempfile
import unittest
from unittest.mock import patch

from autoftbq_v2.ftb.persistence import AtomicBookWriter, write_json_atomic


class FTBPersistenceTests(unittest.TestCase):
    def test_batch_failure_restores_files_already_installed(self):
        with tempfile.TemporaryDirectory() as root:
            first = os.path.join(root, "chapters", "first.snbt")
            second = os.path.join(root, "chapters", "second.snbt")
            os.makedirs(os.path.dirname(first))
            for path, content in ((first, "old-first"), (second, "old-second")):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(content)
            real_replace = os.replace
            calls = 0

            def fail_second(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("disk interrupted")
                return real_replace(source, target)

            with patch("autoftbq_v2.ftb.persistence.os.replace", side_effect=fail_second):
                with self.assertRaises(OSError):
                    AtomicBookWriter().write(root, {first: "new-first", second: "new-second"})

            with open(first, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "old-first")
            with open(second, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "old-second")

    def test_json_writer_replaces_temporary_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "draft.json")
            write_json_atomic(path, {"title": "测试"})

            self.assertTrue(os.path.isfile(path))
            self.assertFalse(os.path.exists(path + ".tmp"))


if __name__ == "__main__":
    unittest.main()
