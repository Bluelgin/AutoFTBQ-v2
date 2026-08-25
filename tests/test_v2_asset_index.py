import base64
import json
import os
import tempfile
import unittest
import zipfile

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage

from autoftbq_v2.infrastructure.asset_index import AssetIndex


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL6WQAAAABJRU5ErkJggg=="
)


def colored_png(color: str) -> bytes:
    image = QImage(16, 16, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    data = QBuffer()
    data.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(data, "PNG")
    return bytes(data.data())


class AssetIndexTests(unittest.TestCase):
    def test_resolves_item_model_texture_from_mod_jar(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            jar_path = os.path.join(mods, "sample.jar")
            with zipfile.ZipFile(jar_path, "w") as archive:
                archive.writestr(
                    "assets/sample/models/item/gear.json",
                    json.dumps({"parent": "minecraft:item/generated", "textures": {"layer0": "sample:item/gear"}}),
                )
                archive.writestr("assets/sample/textures/item/gear.png", PNG)

            index = AssetIndex.build(
                root,
                {"sample": {"sample:gear": "Gear"}},
                os.path.join(root, "cache"),
            )

            self.assertEqual(index.summary()["icons"], 0)
            self.assertEqual(index.summary()["pending"], 1)
            icon = index.icon_for("sample:gear")
            self.assertTrue(os.path.isfile(icon))
            with open(icon, "rb") as handle:
                self.assertEqual(handle.read(), PNG)
            self.assertEqual(index.summary()["icons"], 1)

    def test_child_model_inherits_parent_texture(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "sample.jar"), "w") as archive:
                archive.writestr(
                    "assets/sample/models/item/machine.json",
                    json.dumps({"parent": "sample:block/machine"}),
                )
                archive.writestr(
                    "assets/sample/models/block/machine.json",
                    json.dumps({"textures": {"all": "sample:block/machine"}}),
                )
                archive.writestr("assets/sample/textures/block/machine.png", PNG)

            index = AssetIndex.build(
                root,
                {"sample": {"sample:machine": "Machine"}},
                os.path.join(root, "cache"),
            )

            self.assertTrue(index.icon_for("sample:machine"))

    def test_composites_layered_item_model_on_demand(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "sample.jar"), "w") as archive:
                archive.writestr(
                    "assets/sample/models/item/badge.json",
                    json.dumps({
                        "parent": "minecraft:item/generated",
                        "textures": {
                            "layer0": "sample:item/base",
                            "layer1": "sample:item/overlay",
                        },
                    }),
                )
                archive.writestr("assets/sample/textures/item/base.png", colored_png("#cc4422"))
                archive.writestr("assets/sample/textures/item/overlay.png", colored_png("#4488cc80"))

            index = AssetIndex.build(
                root, {"sample": {"sample:badge": "Badge"}}, os.path.join(root, "cache")
            )
            icon = index.icon_for("sample:badge")

            rendered = QImage(icon)
            self.assertEqual((rendered.width(), rendered.height()), (64, 64))
            self.assertEqual(index.items["sample:badge"].model_kind, "layered")
            self.assertEqual(index.summary()["rendered_models"], 1)

    def test_renders_common_block_model_as_isometric_icon(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "sample.jar"), "w") as archive:
                archive.writestr(
                    "assets/sample/models/item/crate.json",
                    json.dumps({"parent": "sample:block/crate"}),
                )
                archive.writestr(
                    "assets/sample/models/block/crate.json",
                    json.dumps({
                        "parent": "minecraft:block/cube_all",
                        "textures": {"all": "sample:block/crate"},
                    }),
                )
                archive.writestr("assets/sample/textures/block/crate.png", colored_png("#9a6738"))

            index = AssetIndex.build(
                root, {"sample": {"sample:crate": "Crate"}}, os.path.join(root, "cache")
            )
            icon = index.icon_for("sample:crate")

            rendered = QImage(icon)
            self.assertEqual((rendered.width(), rendered.height()), (64, 64))
            self.assertEqual(index.items["sample:crate"].model_kind, "block")
            self.assertGreater(rendered.pixelColor(32, 20).alpha(), 0)

    def test_resolves_arbitrary_image_and_theme_quest_shapes(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "ftbquests.jar"), "w") as archive:
                archive.writestr("assets/ftbquests/textures/gui/banner.png", PNG)
                archive.writestr(
                    "assets/ftbquests/ftb_quests_theme.txt",
                    "extra_quest_shapes: diamond, heart, gear\n",
                )
            index = AssetIndex.build(root, {}, os.path.join(root, "cache"))

            self.assertTrue(os.path.isfile(index.image_for("ftbquests:textures/gui/banner.png")))
            self.assertEqual(index.quest_shapes(), ["diamond", "heart", "gear"])

    def test_indexes_safe_datapack_registries_for_offline_pickers(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "worldgen.jar"), "w") as archive:
                archive.writestr("data/sample/worldgen/biome/crystal_caves.json", "{}")
                archive.writestr("data/sample/dimension/moon.json", "{}")
                archive.writestr("data/sample/advancement/root.json", "{}")
                archive.writestr("data/sample/tags/entity_type/bosses.json", "{}")
            index = AssetIndex.build(root, {}, os.path.join(root, "cache"))

            self.assertIn("sample:crystal_caves", index.registry_values("biome"))
            self.assertIn("sample:moon", index.registry_values("dimension"))
            self.assertEqual(index.search_registry("advancement", "root")[0][0], "sample:root")
            self.assertIn("#sample:bosses", index.registry_values("entity_tag"))

    def test_indexes_mod_entities_and_fluids_from_language_files(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "creatures.jar"), "w") as archive:
                archive.writestr("assets/sample/lang/en_us.json", json.dumps({
                    "entity.sample.clockwork_golem": "Clockwork Golem",
                    "fluid.sample.liquid_mana": "Liquid Mana",
                }))
                archive.writestr("assets/sample/lang/zh_cn.json", json.dumps({
                    "entity.sample.clockwork_golem": "发条傀儡",
                }, ensure_ascii=False))
            index = AssetIndex.build(root, {}, os.path.join(root, "cache"))

            self.assertEqual(index.registry_values("entity")["sample:clockwork_golem"], "发条傀儡")
            self.assertEqual(index.registry_values("fluid")["sample:liquid_mana"], "Liquid Mana")
            self.assertEqual(index.registry_values("dimension")["minecraft:the_nether"], "下界")


if __name__ == "__main__":
    unittest.main()
