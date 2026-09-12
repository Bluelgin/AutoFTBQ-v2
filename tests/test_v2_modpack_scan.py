import os
import tempfile
import unittest
from unittest.mock import patch

from autoftbq_v2.infrastructure.modpack_scan import ModpackScanService


class ModpackScanServiceTests(unittest.TestCase):
    def test_scan_composes_resources_and_optional_quest_book(self):
        with tempfile.TemporaryDirectory() as folder:
            mods = os.path.join(folder, "mods")
            os.makedirs(mods)
            cache = os.path.join(folder, "cache", "icons")
            progress = []
            with (
                patch("autoftbq_v2.infrastructure.modpack_scan.mod_scanner.scan_folder_items", return_value={"minecraft": ["stone"]}) as scan,
                patch("autoftbq_v2.infrastructure.modpack_scan.AssetIndex.build", return_value="assets") as build,
                patch("autoftbq_v2.infrastructure.modpack_scan.locate_quest_root", return_value="quests"),
                patch("autoftbq_v2.infrastructure.modpack_scan.FTBQuestStore.load_directory", return_value="store") as load,
                patch("autoftbq_v2.infrastructure.modpack_scan.mod_scanner._recipe_inputs_cache", {"minecraft:stone": []}, create=True),
            ):
                result = ModpackScanService(cache).scan(folder, progress=progress.append)

            scan.assert_called_once()
            self.assertEqual(scan.call_args.args[0], mods)
            self.assertEqual(build.call_args.args, (
                folder, {"minecraft": ["stone"]}, cache, {"minecraft:stone": []},
            ))
            self.assertIn("progress", build.call_args.kwargs)
            self.assertIn("cancelled", build.call_args.kwargs)
            load.assert_called_once_with("quests", folder)
            self.assertEqual(result["asset_index"], "assets")
            self.assertEqual(result["recipes"], {"minecraft:stone": []})
            self.assertGreaterEqual(len(progress), 3)

    def test_scan_can_restore_resources_without_reloading_quest_book(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = os.path.join(folder, "cache", "icons")
            with (
                patch("autoftbq_v2.infrastructure.modpack_scan.mod_scanner.scan_folder_items", return_value={}),
                patch("autoftbq_v2.infrastructure.modpack_scan.AssetIndex.build", return_value="assets"),
                patch("autoftbq_v2.infrastructure.modpack_scan.locate_quest_root", return_value="quests"),
                patch("autoftbq_v2.infrastructure.modpack_scan.FTBQuestStore.load_directory") as load,
            ):
                result = ModpackScanService(cache).scan(folder, load_quest_book=False)

        load.assert_not_called()
        self.assertIsNone(result["store"])

    def test_second_scan_reuses_persistent_item_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            mods = os.path.join(folder, "mods")
            os.makedirs(mods)
            jar = os.path.join(mods, "example.jar")
            with open(jar, "wb") as handle:
                handle.write(b"fixture")
            cache = os.path.join(folder, "cache", "icons")
            with (
                patch("autoftbq_v2.infrastructure.modpack_scan.mod_scanner.scan_folder_items",
                      return_value={"example": {"example:item": "Item"}}) as scan,
                patch("autoftbq_v2.infrastructure.modpack_scan.AssetIndex.build",
                      return_value="assets"),
                patch("autoftbq_v2.infrastructure.modpack_scan.locate_quest_root",
                      return_value=None),
                patch("autoftbq_v2.infrastructure.modpack_scan.mod_scanner._recipe_inputs_cache",
                      {"example:item": []}, create=True),
            ):
                service = ModpackScanService(cache)
                first = service.scan(folder)
                second = service.scan(folder)

            self.assertEqual(scan.call_count, 1)
            self.assertEqual(second["items"], first["items"])
            self.assertEqual(second["recipes"], first["recipes"])


if __name__ == "__main__":
    unittest.main()
