import json
import os
import tempfile
import unittest

from snbt_parser import parse_snbt, to_snbt

from autoftbq_v2.ftb_store import FTBQuestStore, locate_quest_root
from autoftbq_v2.agent import ProjectAgent


CHAPTER = {
    "id": "1000000000000001",
    "filename": "1000000000000001",
    "title": "Real chapter",
    "icon": {"id": "minecraft:book", "count": 1},
    "unknown_chapter_field": {"keep": "yes"},
    "quests": [
        {
            "id": "2000000000000001",
            "title": "First",
            "subtitle": "Before",
            "x": 1.0,
            "y": 2.0,
            "shape": "diamond",
            "dependencies": [],
            "unknown_quest_field": 77,
            "tasks": [
                {"id": "3000000000000001", "type": "item", "item": {"id": "minecraft:stone", "components": {"x": 1}}, "count": 2, "extra": True},
                {"id": "3000000000000002", "type": "checkmark", "custom": "untouched"},
            ],
            "rewards": [{"id": "4000000000000001", "type": "custom", "custom_data": {"keep": 1}}],
            "description": ["Line one"],
        }
    ],
}


class FTBQuestStoreTests(unittest.TestCase):
    def test_workspace_snapshot_preserves_unsaved_real_book_without_writing_source(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root = os.path.join(root, "config", "ftbquests", "quests")
            chapters = os.path.join(quest_root, "chapters")
            os.makedirs(chapters)
            chapter_path = os.path.join(chapters, "chapter.snbt")
            with open(chapter_path, "w", encoding="utf-8") as handle:
                handle.write(to_snbt(CHAPTER))
            store = FTBQuestStore.load_directory(quest_root, root)
            quest = store.project.chapters[0].quests[0]
            store.update_quest(quest.id, title="尚未写回游戏")
            snapshot = os.path.join(root, "workspace", "draft.autoftbq.json")

            store.save_workspace(snapshot)
            with open(chapter_path, encoding="utf-8") as handle:
                self.assertEqual(parse_snbt(handle.read())["quests"][0]["title"], "First")

            restored = FTBQuestStore.load_workspace(snapshot)
            self.assertTrue(restored.is_real)
            self.assertEqual(restored.project.chapters[0].quests[0].title, "尚未写回游戏")
            self.assertIn(restored.project.chapters[0].id, restored.dirty_chapters)

    def test_new_project_uses_full_conditions_and_round_trips_project_file(self):
        store = FTBQuestStore.create_new("完整条件测试")
        quest = store.project.chapters[0].quests[0]
        store.add_quest_object(quest.id, "task", "kill", {
            "entity": "minecraft:wither", "value": 1,
        })
        store.add_quest_object(quest.id, "task", "dimension", {
            "dimension": "minecraft:the_end",
        })

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "book.autoftbq.json")
            store.save(path)
            loaded = FTBQuestStore.load_project(path)

            loaded_quest = loaded.project.chapters[0].quests[0]
            tasks, _rewards = loaded.raw_sections(loaded_quest.id)
            self.assertFalse(loaded.is_real)
            self.assertEqual([task["type"] for task in tasks], ["checkmark", "kill", "dimension"])
            self.assertEqual(tasks[1]["entity"], "minecraft:wither")
            self.assertEqual(tasks[2]["dimension"], "minecraft:the_end")
            self.assertFalse(any(issue["severity"] == "error" for issue in loaded.validate()))

    def test_full_project_export_preserves_typed_conditions(self):
        store = FTBQuestStore.create_new(with_starter=False)
        chapter = store.create_chapter("探索")
        quest = store.add_quest(chapter.id, "前往下界", task_type="dimension", target="minecraft:the_nether")
        store.add_quest_object(quest.id, "task", "kill", {
            "entity": "minecraft:blaze", "value": 5,
        })

        with tempfile.TemporaryDirectory() as root:
            result = store.export_directory(root)
            chapter_path = os.path.join(root, "chapters", f"{chapter.id}.snbt")
            with open(chapter_path, "r", encoding="utf-8") as handle:
                raw = parse_snbt(handle.read())

            self.assertGreaterEqual(result["saved"], 3)
            self.assertEqual(raw["quests"][0]["tasks"][0]["dimension"], "minecraft:the_nether")
            self.assertEqual(raw["quests"][0]["tasks"][1]["entity"], "minecraft:blaze")

    def test_legacy_project_is_upgraded_to_full_ftb_ids(self):
        from autoftbq_v2.project import Chapter, Quest, QuestBookProject, Task

        old = QuestBookProject(
            title="旧项目",
            chapters=[Chapter(id="chapter_old", title="旧章节", quests=[
                Quest(id="quest_old", title="旧任务", tasks=[Task("kill", "minecraft:zombie", 3)]),
            ])],
        )
        upgraded = FTBQuestStore.from_project(old)
        quest = upgraded.project.chapters[0].quests[0]
        tasks, _ = upgraded.raw_sections(quest.id)

        self.assertRegex(quest.id, r"^[0-9A-F]{16}$")
        self.assertEqual(tasks[0]["type"], "kill")
        self.assertEqual(tasks[0]["entity"], "minecraft:zombie")
        self.assertEqual(tasks[0]["value"], 3)

    def make_book(self, root):
        quest_root = os.path.join(root, "config", "ftbquests", "quests")
        chapters = os.path.join(quest_root, "chapters")
        os.makedirs(chapters)
        path = os.path.join(chapters, "1000000000000001.snbt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(to_snbt(CHAPTER))
        return quest_root, path

    def make_complete_book(self, root):
        quest_root, chapter_path = self.make_book(root)
        with open(os.path.join(quest_root, "data.snbt"), "w", encoding="utf-8") as handle:
            handle.write(to_snbt({"version": 13, "default_reward_team": True, "addon_setting": {"keep": 1}}))
        with open(os.path.join(quest_root, "chapter_groups.snbt"), "w", encoding="utf-8") as handle:
            handle.write(to_snbt({"chapter_groups": [{"id": "10", "title": "Main", "addon": 2}]}))
        reward_dir = os.path.join(quest_root, "reward_tables")
        os.makedirs(reward_dir)
        with open(os.path.join(reward_dir, "table.snbt"), "w", encoding="utf-8") as handle:
            handle.write(to_snbt({"id": "20", "rewards": [], "unknown_table_field": 3}))
        return quest_root, chapter_path

    def test_locates_and_loads_real_book(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_book(root)
            self.assertEqual(locate_quest_root(root), quest_root)
            store = FTBQuestStore.load_directory(quest_root, root)
            quest = store.project.chapters[0].quests[0]
            self.assertEqual(quest.x, 1.0)
            self.assertEqual(quest.tasks[0].target, "minecraft:stone")
            self.assertEqual(len(quest.tasks), 2)

    def test_edits_real_fields_and_preserves_unknown_snbt(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, path = self.make_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            quest = store.project.chapters[0].quests[0]

            store.update_quest(
                quest.id, title="Changed", subtitle="After", task_type="item",
                target="minecraft:diamond", count=3, shape="hexagon",
            )
            store.move_quest(quest.id, 4.5, -2.0)
            result = store.save_all()

            self.assertEqual(result["saved"], 1)
            self.assertTrue(os.path.isdir(result["backup"]))
            with open(path, "r", encoding="utf-8") as handle:
                raw = parse_snbt(handle.read())
            saved = raw["quests"][0]
            self.assertEqual(saved["title"], "Changed")
            self.assertEqual(saved["x"], 4.5)
            self.assertEqual(saved["tasks"][0]["item"]["id"], "minecraft:diamond")
            self.assertEqual(saved["tasks"][0]["item"]["components"], {"x": 1})
            self.assertEqual(saved["tasks"][1]["custom"], "untouched")
            self.assertEqual(saved["rewards"][0]["custom_data"], {"keep": 1})
            self.assertEqual(saved["unknown_quest_field"], 77)
            self.assertEqual(raw["unknown_chapter_field"], {"keep": "yes"})

    def test_undo_restores_raw_sections_and_view(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            quest = store.project.chapters[0].quests[0]
            store.replace_quest_sections(quest.id, [{"id": "5", "type": "kill", "entity": "minecraft:zombie"}], [])
            self.assertEqual(store.quest(quest.id)[1].tasks[0].type, "kill")
            self.assertTrue(store.undo())
            self.assertEqual(store.quest(quest.id)[1].tasks[0].type, "item")
            self.assertEqual(store.raw_sections(quest.id)[0][0]["extra"], True)

    def test_default_shape_is_saved_by_removing_shape_field(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, path = self.make_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            quest = store.project.chapters[0].quests[0]

            store.update_quest(quest.id, shape="")
            store.save_all()

            with open(path, "r", encoding="utf-8") as handle:
                saved = parse_snbt(handle.read())["quests"][0]
            self.assertNotIn("shape", saved)

    def test_agent_tools_edit_same_real_document(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            quest = store.project.chapters[0].quests[0]
            agent = ProjectAgent(store, None)

            result = agent.call_tool("replace_quest_sections", {
                "quest_id": quest.id,
                "rewards": [{"id": "5000000000000001", "type": "xp", "xp": 50}],
            })

            self.assertIn('"rewards":1', result)
            self.assertEqual(store.raw_sections(quest.id)[1][0]["xp"], 50)
            self.assertIn(store.project.chapters[0].id, store.dirty_chapters)

    def test_supporting_documents_round_trip_with_unknown_fields(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)

            self.assertEqual(store.document("data.snbt")["addon_setting"], {"keep": 1})
            self.assertEqual(store.list_reward_tables()[0]["data"]["unknown_table_field"], 3)
            store.update_document("data.snbt", {"grid_scale": 1.5})
            store.update_document(os.path.join("reward_tables", "table.snbt"), {"loot_size": 2})
            result = store.save_all()

            self.assertEqual(result["saved"], 2)
            with open(os.path.join(quest_root, "data.snbt"), encoding="utf-8") as handle:
                data = parse_snbt(handle.read())
            with open(os.path.join(quest_root, "reward_tables", "table.snbt"), encoding="utf-8") as handle:
                table = parse_snbt(handle.read())
            self.assertEqual(data["grid_scale"], 1.5)
            self.assertEqual(data["addon_setting"], {"keep": 1})
            self.assertEqual(table["loot_size"], 2)
            self.assertEqual(table["unknown_table_field"], 3)

    def test_generic_task_and_reward_commands_preserve_extension_fields(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, path = self.make_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            quest = store.project.chapters[0].quests[0]

            task = store.add_quest_object(quest.id, "task", "location", {
                "dimension": "minecraft:overworld",
                "position": [1, 64, 2],
                "size": [5, 3, 5],
                "addon_field": {"keep": True},
            })
            reward = store.add_quest_object(quest.id, "reward", "command", {
                "command": "/say hi", "silent": True,
            })
            store.update_quest_object(quest.id, "task", task["id"], {"ignore_dimension": True})
            store.move_quest_object(quest.id, "task", task["id"], 0)
            store.update_quest_object(quest.id, "reward", reward["id"], {"permission_level": 4})
            store.save_all()

            with open(path, encoding="utf-8") as handle:
                saved = parse_snbt(handle.read())["quests"][0]
            self.assertEqual(saved["tasks"][0]["type"], "location")
            self.assertEqual(saved["tasks"][0]["position"], [1, 64, 2])
            self.assertEqual(saved["tasks"][0]["addon_field"], {"keep": True})
            self.assertTrue(saved["tasks"][0]["ignore_dimension"])
            command = next(value for value in saved["rewards"] if value["id"] == reward["id"])
            self.assertEqual(command["permission_level"], 4)
            self.assertTrue(command["silent"])

    def test_agent_uses_schema_and_granular_commands_on_real_document(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, chapter_path = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            quest = store.project.chapters[0].quests[0]
            agent = ProjectAgent(store, None)

            schema = json.loads(agent.call_tool("get_ftb_schema", {"kind": "task", "type_id": "kill"}))
            added = json.loads(agent.call_tool("add_quest_object", {
                "quest_id": quest.id, "kind": "task", "type_id": "kill",
                "values": {"entity": "minecraft:zombie", "value": 5},
            }))
            agent.call_tool("update_quest_object", {
                "quest_id": quest.id, "kind": "task", "object_id": added["id"],
                "changes": {"custom_name": "Test zombie"},
            })
            agent.call_tool("update_book_document", {
                "path": "data.snbt", "changes": {"detection_delay": 10},
            })

            self.assertIn("entity", {field["key"] for field in schema["fields"]})
            tasks, _ = store.raw_sections(quest.id)
            kill = next(task for task in tasks if task["id"] == added["id"])
            self.assertEqual(kill["custom_name"], "Test zombie")
            self.assertEqual(store.document("data.snbt")["detection_delay"], 10)
            store.save_all()
            with open(chapter_path, encoding="utf-8") as handle:
                saved_tasks = parse_snbt(handle.read())["quests"][0]["tasks"]
            saved_kill = next(task for task in saved_tasks if task["id"] == added["id"])
            self.assertEqual(saved_kill["value"], 5)
            self.assertNotIn("count", saved_kill)

    def test_full_quest_chapter_and_canvas_properties_are_patched_losslessly(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, chapter_path = self.make_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            chapter = store.project.chapters[0]
            quest = chapter.quests[0]

            store.update_quest_fields(quest.id, {
                "can_repeat": True,
                "repeat_cooldown": 1200,
                "dependency_requirement": "one_started",
                "size": 1.5,
                "addon_quest_setting": {"keep": 9},
            })
            store.update_chapter_fields(chapter.id, {
                "require_sequential_tasks": True,
                "hide_quest_until_deps_complete": True,
            })
            image = store.add_chapter_object(chapter.id, "image", {
                "image": "minecraft:textures/item/book.png", "x": 2.0, "y": 3.0,
                "width": 4.0, "height": 2.0, "addon_image_field": "keep",
            })
            store.update_chapter_object(chapter.id, "image", image["id"], {"rotation": 15.0})
            store.save_all()

            with open(chapter_path, encoding="utf-8") as handle:
                saved = parse_snbt(handle.read())
            saved_quest = saved["quests"][0]
            self.assertTrue(saved_quest["can_repeat"])
            self.assertEqual(saved_quest["dependency_requirement"], "one_started")
            self.assertEqual(saved_quest["addon_quest_setting"], {"keep": 9})
            self.assertTrue(saved["require_sequential_tasks"])
            self.assertEqual(saved["images"][0]["rotation"], 15.0)
            self.assertEqual(saved["images"][0]["addon_image_field"], "keep")

    def test_whole_book_validation_finds_global_ids_references_and_cycles(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            chapter = store.project.chapters[0]
            first = chapter.quests[0]
            second = store.add_quest(chapter.id, "Second")
            store.connect(second.id, first.id)
            store.raw_quests[first.id]["dependencies"] = [second.id]
            first.dependencies = [second.id]
            duplicate_reward = {
                "id": store.raw_quests[first.id]["tasks"][0]["id"],
                "type": "random", "table_id": "missing-table",
            }
            store.raw_quests[first.id]["rewards"].append(duplicate_reward)
            first.rewards.append(dict(duplicate_reward))

            messages = [issue["message"] for issue in store.validate()]

            self.assertIn("任务前置关系存在循环", messages)
            self.assertTrue(any(message.startswith("ID 与 ") for message in messages))
            self.assertIn("奖励表不存在：missing-table", messages)

    def test_unknown_addon_task_type_is_preserved_without_false_required_field_error(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            quest = store.project.chapters[0].quests[0]
            store.add_quest_object(quest.id, "task", "example:energy", {"energy": 5000})

            messages = [issue["message"] for issue in store.validate()]

            self.assertFalse(any("example:energy 缺少字段" in message for message in messages))

    def test_newer_file_version_is_reported_but_remains_editable(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            store.update_document("data.snbt", {"version": 999, "future_field": {"keep": True}})

            issues = store.validate()

            self.assertTrue(any("高于当前已核对版本" in issue["message"] for issue in issues))
            self.assertEqual(store.summary()["file_version"], 999)
            self.assertEqual(store.document("data.snbt")["future_field"], {"keep": True})

    def test_chapter_groups_and_reward_tables_have_full_crud_and_transactional_delete(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)

            group = store.add_document_object("chapter_groups.snbt", "chapter_groups", {
                "title": "Extra", "unknown_group": {"keep": 1},
            })
            table = store.create_reward_table("Treasure")
            reward = store.add_document_object(table["path"], "rewards", {
                "type": "item", "item": {"id": "minecraft:diamond", "count": 1},
                "weight": 2.5, "unknown_reward": True,
            })
            store.update_document_object(table["path"], "rewards", reward["id"], {"weight": 3.0})
            first_save = store.save_all()

            table_path = os.path.join(quest_root, table["path"])
            self.assertTrue(os.path.isfile(table_path))
            self.assertGreaterEqual(first_save["saved"], 2)
            reloaded = FTBQuestStore.load_directory(quest_root, root)
            groups = reloaded.document_objects("chapter_groups.snbt", "chapter_groups")
            self.assertEqual(next(value for value in groups if value["id"] == group["id"])["unknown_group"], {"keep": 1})
            saved_reward = reloaded.document_objects(table["path"], "rewards")[0]
            self.assertEqual(saved_reward["weight"], 3.0)
            self.assertTrue(saved_reward["unknown_reward"])

            self.assertTrue(reloaded.remove_document(table["path"]))
            result = reloaded.save_all()
            self.assertFalse(os.path.exists(table_path))
            self.assertTrue(os.path.isfile(os.path.join(result["backup"], table["path"])))

    def test_document_commands_reject_paths_outside_quest_root(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)

            with self.assertRaises(ValueError):
                store.add_document_object(os.path.join("..", "outside.snbt"), "values", {})

    def test_removing_chapter_group_reassigns_its_chapters_to_default(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, chapter_path = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            chapter = store.project.chapters[0]
            group = store.create_chapter_group("Temporary")
            store.update_chapter_fields(chapter.id, {"group": group["id"]})

            self.assertTrue(store.remove_chapter_group(group["id"]))
            store.save_all()

            with open(chapter_path, encoding="utf-8") as handle:
                saved = parse_snbt(handle.read())
            self.assertEqual(saved["group"], "")
            groups = store.document_objects("chapter_groups.snbt", "chapter_groups")
            self.assertNotIn(group["id"], {value["id"] for value in groups})

    def test_chapter_reorder_cross_chapter_move_and_delete_are_lossless(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            first = store.project.chapters[0]
            original = first.quests[0]
            second = store.create_chapter("Second")
            second_path = store.chapter_files[second.id]

            store.move_quest_to_chapter(original.id, second.id, 7.0, -2.0)
            store.move_chapter(second.id, 0)
            dependent = store.add_quest(first.id, "Depends on moved")
            store.connect(dependent.id, original.id)
            link = store.add_chapter_object(first.id, "link", {
                "linked_quest": original.id, "x": 1.0, "y": 1.0,
            })
            store.save_all()

            moved_raw = store.quest_data(original.id)
            self.assertEqual(moved_raw["unknown_quest_field"], 77)
            self.assertEqual((store.quest(original.id)[1].x, store.quest(original.id)[1].y), (7.0, -2.0))
            self.assertEqual(store.raw_chapters[second.id]["order_index"], 0)
            self.assertTrue(os.path.isfile(second_path))

            self.assertTrue(store.remove_chapter(second.id))
            self.assertEqual(store.quest(dependent.id)[1].dependencies, [])
            self.assertNotIn(link["id"], {
                value.get("id") for value in store.chapter_data(first.id).get("quest_links", [])
            })
            result = store.save_all()
            self.assertFalse(os.path.exists(second_path))
            self.assertTrue(os.path.isfile(os.path.join(result["backup"], "chapters", os.path.basename(second_path))))

    def test_agent_exposes_structural_chapter_commands(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            agent = ProjectAgent(store, None)
            names = {value["function"]["name"] for value in agent.tool_specs()}
            self.assertTrue({"remove_chapter", "move_chapter", "move_quest_to_chapter"}.issubset(names))

            created = json.loads(agent.call_tool("create_chapter", {"title": "Agent chapter"}))
            quest_id = store.project.chapters[0].quests[0].id
            moved = json.loads(agent.call_tool("move_quest_to_chapter", {
                "quest_id": quest_id, "chapter_id": created["chapter_id"], "x": 4, "y": 5,
            }))
            self.assertEqual(moved["chapter_id"], created["chapter_id"])
            self.assertEqual(store.quest(quest_id)[0].id, created["chapter_id"])

    def test_native_translation_files_are_loaded_edited_and_cleaned(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, chapter_path = self.make_complete_book(root)
            lang_chapters = os.path.join(quest_root, "lang", "en_us", "chapters")
            os.makedirs(lang_chapters)
            lang_path = os.path.join(lang_chapters, os.path.basename(chapter_path))
            with open(lang_path, "w", encoding="utf-8") as handle:
                handle.write(to_snbt({
                    "quest.2000000000000001.title": "First translated",
                    "addon.keep": "untouched",
                }))
            store = FTBQuestStore.load_directory(quest_root, root)

            self.assertEqual(store.list_locales(), ["en_us"])
            self.assertEqual(
                store.translation_entries("en_us")["quest.2000000000000001.title"],
                "First translated",
            )
            store.update_translation(
                "en_us", "quest", "2000000000000001", "quest_desc", ["Translated description"],
            )
            store.update_translation(
                "zh_cn", "quest", "2000000000000001", "title", "中文标题",
            )
            store.save_all()

            reloaded = FTBQuestStore.load_directory(quest_root, root)
            self.assertEqual(reloaded.list_locales(), ["en_us", "zh_cn"])
            self.assertEqual(
                reloaded.translation_entries("en_us")["quest.2000000000000001.quest_desc"],
                ["Translated description"],
            )
            self.assertEqual(reloaded.translation_entries("en_us")["addon.keep"], "untouched")
            self.assertTrue(reloaded.remove_quest("2000000000000001"))
            reloaded.save_all()
            final = FTBQuestStore.load_directory(quest_root, root)
            self.assertNotIn("quest.2000000000000001.title", final.translation_entries("en_us"))
            self.assertNotIn("quest.2000000000000001.title", final.translation_entries("zh_cn"))

    def test_copy_quest_rekeys_children_and_preserves_raw_data_and_translations(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            chapter = store.project.chapters[0]
            source = chapter.quests[0]
            source_raw = store.quest_data(source.id)
            store.update_translation("en_us", "quest", source.id, "title", "Translated source")
            store.update_translation(
                "en_us", "task", source_raw["tasks"][0]["id"], "title", "Translated task",
            )

            copied = store.copy_quest(source.id, chapter.id, 8.0, 9.0, with_dependencies=False)
            copied_raw = store.quest_data(copied.id)
            old_ids = {source.id, *(value["id"] for value in source_raw["tasks"] + source_raw["rewards"])}
            new_ids = {copied.id, *(value["id"] for value in copied_raw["tasks"] + copied_raw["rewards"])}

            self.assertTrue(old_ids.isdisjoint(new_ids))
            self.assertEqual(copied_raw["unknown_quest_field"], 77)
            self.assertEqual(copied.dependencies, [])
            self.assertEqual((copied.x, copied.y), (8.0, 9.0))
            translations = store.translation_entries("en_us")
            self.assertEqual(translations[f"quest.{copied.id}.title"], "Translated source")
            self.assertEqual(translations[f"task.{copied_raw['tasks'][0]['id']}.title"], "Translated task")

    def test_batch_canvas_delete_is_one_undo_step(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root, _ = self.make_complete_book(root)
            store = FTBQuestStore.load_directory(quest_root, root)
            chapter = store.project.chapters[0]
            quest = store.add_quest(chapter.id, "Temporary")
            image = store.add_chapter_object(chapter.id, "image", {
                "image": "minecraft:textures/item/book.png", "x": 0.0, "y": 0.0,
                "width": 1.0, "height": 1.0,
            })

            removed = store.remove_canvas_objects(chapter.id, [
                ("quest", quest.id), ("image", image["id"]),
            ])

            self.assertEqual(removed, 2)
            self.assertIsNone(store.quest(quest.id))
            self.assertEqual(store.chapter_data(chapter.id).get("images", []), [])
            self.assertTrue(store.undo())
            self.assertIsNotNone(store.quest(quest.id))
            self.assertEqual(store.chapter_data(chapter.id)["images"][0]["id"], image["id"])


if __name__ == "__main__":
    unittest.main()
