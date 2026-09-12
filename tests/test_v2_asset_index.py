import base64
import json
import os
import tempfile
import time
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
    def test_agent_whitelist_requires_complete_model_and_gameplay_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "sample.jar"), "w") as archive:
                for item_id in ("safe_gear", "decorative_gear"):
                    archive.writestr(
                        f"assets/sample/models/item/{item_id}.json",
                        json.dumps({
                            "parent": "minecraft:item/generated",
                            "textures": {"layer0": f"sample:item/{item_id}"},
                        }),
                    )
                    archive.writestr(f"assets/sample/textures/item/{item_id}.png", PNG)
                archive.writestr("assets/sample/textures/item/texture_only.png", PNG)
                archive.writestr(
                    "assets/sample/models/item/broken_gear.json",
                    json.dumps({
                        "parent": "minecraft:item/generated",
                        "textures": {"layer0": "sample:item/not_shipped"},
                    }),
                )
            items = {"sample": {
                "sample:safe_gear": "Safe Gear",
                "sample:decorative_gear": "Decorative Gear",
                "sample:texture_only": "Texture Only",
                "sample:broken_gear": "Broken Gear",
            }}
            recipes = {"sample:safe_gear": ["minecraft:iron_ingot"]}

            index = AssetIndex.build(root, items, os.path.join(root, "cache"), recipes)

            self.assertTrue(index.agent_item_status("sample:safe_gear").allowed)
            self.assertEqual(index.agent_item_status("sample:decorative_gear").status, "uncertain")
            self.assertIn("缺少物品模型", index.agent_item_status("sample:texture_only").reasons)
            self.assertIn("贴图不存在", index.agent_item_status("sample:broken_gear").reasons[0])

    def test_agent_whitelist_accepts_loot_output_with_complete_model(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "sample.jar"), "w") as archive:
                archive.writestr(
                    "assets/sample/models/item/boss_core.json",
                    json.dumps({
                        "parent": "minecraft:item/generated",
                        "textures": {"layer0": "sample:item/boss_core"},
                    }),
                )
                archive.writestr("assets/sample/textures/item/boss_core.png", PNG)
                archive.writestr(
                    "data/sample/loot_tables/entities/boss.json",
                    json.dumps({
                        "pools": [{"entries": [{
                            "type": "minecraft:item", "name": "sample:boss_core",
                        }]}],
                    }),
                )

            index = AssetIndex.build(
                root, {"sample": {"sample:boss_core": "Boss Core"}},
                os.path.join(root, "cache"), {},
            )

            status = index.agent_item_status("sample:boss_core")
            self.assertTrue(status.allowed)
            self.assertIn("战利品产物", status.evidence)

    def test_resource_atlas_adds_texture_only_items_missed_by_registry_scan(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "sample.jar"), "w") as archive:
                archive.writestr("assets/sample/textures/item/hidden_relic.png", PNG)

            index = AssetIndex.build(root, {}, os.path.join(root, "cache"))

            self.assertIn("sample:hidden_relic", index.items)
            self.assertTrue(index.icon_for("sample:hidden_relic"))

    def test_builtin_entity_model_uses_direct_representative_texture(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "sample.jar"), "w") as archive:
                archive.writestr(
                    "assets/sample/models/item/trophy.json",
                    json.dumps({"parent": "builtin/entity"}),
                )
                archive.writestr("assets/sample/textures/item/trophy.png", PNG)

            index = AssetIndex.build(root, {}, os.path.join(root, "cache"))
            icon = index.icon_for("sample:trophy")

            self.assertTrue(os.path.isfile(icon))
            self.assertEqual(index.items["sample:trophy"].model_kind, "dynamic_fallback")

    def test_spawn_egg_without_texture_gets_deterministic_representative_icon(self):
        with tempfile.TemporaryDirectory() as root:
            index = AssetIndex.build(
                root, {"sample": {"sample:boss_spawn_egg": "Boss Spawn Egg"}},
                os.path.join(root, "cache"),
            )

            icon = index.icon_for("sample:boss_spawn_egg")

            self.assertTrue(os.path.isfile(icon))
            self.assertEqual(index.items["sample:boss_spawn_egg"].model_kind, "spawn_egg_fallback")
            self.assertIn("颜色可能不同", index.icon_status_text("sample:boss_spawn_egg"))

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
            self.assertEqual(index.cached_icon_for("sample:gear"), "")
            icon = index.icon_for("sample:gear")
            self.assertTrue(os.path.isfile(icon))
            with open(icon, "rb") as handle:
                self.assertEqual(handle.read(), PNG)
            self.assertEqual(index.summary()["icons"], 1)
            self.assertEqual(index.cached_icon_for("sample:gear"), icon)

    def test_disk_cache_cleanup_removes_old_icons_but_keeps_recent_files(self):
        with tempfile.TemporaryDirectory() as root:
            cache_root = os.path.join(root, "cache")
            cache_dir = os.path.join(cache_root, "old-pack")
            os.makedirs(cache_dir)
            old_path = os.path.join(cache_dir, "old.png")
            fresh_path = os.path.join(cache_dir, "fresh.png")
            for path in (old_path, fresh_path):
                with open(path, "wb") as handle:
                    handle.write(PNG)
            old_time = time.time() - 3600
            os.utime(old_path, (old_time, old_time))
            index = AssetIndex(root, cache_root)

            result = index.cleanup_cache(max_age_seconds=60, max_bytes=1024 * 1024)

            self.assertEqual(result["removed"], 1)
            self.assertFalse(os.path.exists(old_path))
            self.assertTrue(os.path.exists(fresh_path))

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

    def test_json_cache_round_trip_preserves_resources_and_safety_policy(self):
        with tempfile.TemporaryDirectory() as root:
            mods = os.path.join(root, "mods")
            os.makedirs(mods)
            with zipfile.ZipFile(os.path.join(mods, "sample.jar"), "w") as archive:
                archive.writestr(
                    "assets/sample/models/item/relic.json",
                    json.dumps({
                        "parent": "minecraft:item/generated",
                        "textures": {"layer0": "sample:item/relic"},
                    }),
                )
                archive.writestr("assets/sample/textures/item/relic.png", PNG)
            cache = os.path.join(root, "cache")
            original = AssetIndex.build(
                root, {"sample": {"sample:relic": "Relic"}}, cache,
                {"sample:relic": ["minecraft:iron_ingot"]},
            )

            restored = AssetIndex.from_cache_payload(root, cache, original.cache_payload())

            self.assertEqual(restored.summary()["resources"], original.summary()["resources"])
            self.assertTrue(restored.agent_item_status("sample:relic").allowed)
            self.assertTrue(os.path.isfile(restored.icon_for("sample:relic")))


if __name__ == "__main__":
    unittest.main()
