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
            progress = []
            with (
                patch("autoftbq_v2.infrastructure.modpack_scan.mod_scanner.scan_folder_items", return_value={"minecraft": ["stone"]}) as scan,
                patch("autoftbq_v2.infrastructure.modpack_scan.AssetIndex.build", return_value="assets") as build,
                patch("autoftbq_v2.infrastructure.modpack_scan.locate_quest_root", return_value="quests"),
                patch("autoftbq_v2.infrastructure.modpack_scan.FTBQuestStore.load_directory", return_value="store") as load,
                patch("autoftbq_v2.infrastructure.modpack_scan.mod_scanner._recipe_inputs_cache", {"minecraft:stone": []}, create=True),
            ):
                result = ModpackScanService("cache").scan(folder, progress=progress.append)

            scan.assert_called_once()
            self.assertEqual(scan.call_args.args[0], mods)
            build.assert_called_once_with(folder, {"minecraft": ["stone"]}, "cache")
            load.assert_called_once_with("quests", folder)
            self.assertEqual(result["asset_index"], "assets")
            self.assertEqual(result["recipes"], {"minecraft:stone": []})
            self.assertGreaterEqual(len(progress), 3)

    def test_scan_can_restore_resources_without_reloading_quest_book(self):
        with tempfile.TemporaryDirectory() as folder:
            with (
                patch("autoftbq_v2.infrastructure.modpack_scan.mod_scanner.scan_folder_items", return_value={}),
                patch("autoftbq_v2.infrastructure.modpack_scan.AssetIndex.build", return_value="assets"),
                patch("autoftbq_v2.infrastructure.modpack_scan.locate_quest_root", return_value="quests"),
                patch("autoftbq_v2.infrastructure.modpack_scan.FTBQuestStore.load_directory") as load,
            ):
                result = ModpackScanService("cache").scan(folder, load_quest_book=False)

        load.assert_not_called()
        self.assertIsNone(result["store"])


if __name__ == "__main__":
    unittest.main()
