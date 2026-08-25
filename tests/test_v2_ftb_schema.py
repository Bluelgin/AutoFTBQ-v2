import unittest

from autoftbq_v2.ftb.schema import (
    BOOK_FIELDS,
    CHAPTER_FIELDS,
    CORE_QUEST_SHAPES,
    DEFAULT_THEME_QUEST_SHAPES,
    QUEST_FIELDS,
    REWARD_TYPES,
    TASK_TYPES,
    object_spec,
    schema_catalog,
)


class FTBQuestSchemaTests(unittest.TestCase):
    def test_all_official_core_task_and_reward_types_are_registered(self):
        self.assertEqual(
            set(TASK_TYPES),
            {"item", "custom", "xp", "dimension", "stat", "kill", "location", "checkmark", "advancement", "observation", "biome", "structure", "gamestage", "fluid", "forge_energy", "tech_reborn_energy"},
        )
        self.assertEqual(
            set(REWARD_TYPES),
            {"item", "choice", "all_table", "random", "loot", "command", "custom", "xp", "xp_levels", "advancement", "toast", "gamestage", "currency"},
        )

    def test_unknown_addon_type_gets_generic_lossless_spec(self):
        spec = object_spec("task", "example:energy")
        self.assertEqual(spec.type_id, "example:energy")
        self.assertEqual(spec.fields, ())

    def test_catalog_exposes_all_authoring_layers_to_ui_and_agent(self):
        catalog = schema_catalog()
        self.assertEqual(len(catalog["tasks"]), len(TASK_TYPES))
        self.assertEqual(len(catalog["rewards"]), len(REWARD_TYPES))
        self.assertEqual(catalog["core_shapes"], list(CORE_QUEST_SHAPES))
        self.assertEqual(catalog["default_theme_shapes"], list(DEFAULT_THEME_QUEST_SHAPES))
        self.assertIn("dep_control_pts", {field["key"] for field in catalog["quest_fields"]})
        self.assertIn("click_action", {field["key"] for field in catalog["chapter_image_fields"]})
        self.assertGreater(len(QUEST_FIELDS), 15)
        self.assertGreater(len(CHAPTER_FIELDS), 10)
        self.assertGreater(len(BOOK_FIELDS), 10)


if __name__ == "__main__":
    unittest.main()
