"""Tool schemas exposed by the AutoFTBQ project Agent."""

from __future__ import annotations

from ..ftb.schema import TASK_TYPES as FTB_TASK_TYPES


def build_tool_specs() -> list[dict]:
    def spec(name, description, properties, required=()):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(required),
                },
            },
        }

    return [
        spec("get_project_summary", "Inspect chapters and quest counts.", {}),
        spec("get_chapter_quests", "Inspect quest IDs, titles, coordinates and dependencies in one chapter.", {
            "chapter_id": {"type": "string"},
        }, ("chapter_id",)),
        spec("get_ftb_schema", "Read official editable fields. Use kind=all, task, reward, quest, chapter, or book.", {
            "kind": {"type": "string"}, "type_id": {"type": "string"},
        }),
        spec("list_skills", "List built-in quest-authoring skills and their triggers.", {}),
        spec("load_skill", "Load one relevant built-in workflow before planning or repairing.", {
            "skill_id": {"type": "string"},
        }, ("skill_id",)),
        spec("create_chapter", "Create one chapter.", {
            "title": {"type": "string"}, "icon": {"type": "string"},
        }, ("title",)),
        spec("remove_chapter", "Remove one chapter, its quests, and dangling references. Undoable until save history is closed.", {
            "chapter_id": {"type": "string"},
        }, ("chapter_id",)),
        spec("move_chapter", "Move one chapter to an exact zero-based order index.", {
            "chapter_id": {"type": "string"}, "new_index": {"type": "integer"},
        }, ("chapter_id", "new_index")),
        spec("add_quest", "Add one quest to an existing chapter.", {
            "chapter_id": {"type": "string"}, "title": {"type": "string"},
            "description": {"type": "string"},
            "task_type": {"type": "string", "enum": list(FTB_TASK_TYPES)},
            "target": {"type": "string"}, "count": {"type": "integer"},
        }, ("chapter_id", "title", "task_type")),
        spec("add_quest_chain", "Atomically create 1-12 ordered quests, connect them as one chain, and wrap the visual layout into rows. Prefer this for complete mainline stages.", {
            "chapter_id": {"type": "string"},
            "quests": {
                "type": "array", "minItems": 1, "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"}, "description": {"type": "string"},
                        "task_type": {"type": "string", "enum": list(FTB_TASK_TYPES)},
                        "target": {"type": "string"}, "count": {"type": "integer"},
                    },
                    "required": ["title", "task_type"],
                },
            },
            "start_dependency_id": {"type": "string"},
            "row_width": {"type": "integer", "minimum": 2, "maximum": 8},
        }, ("chapter_id", "quests")),
        spec("update_quest", "Update one existing quest.", {
            "quest_id": {"type": "string"}, "title": {"type": "string"},
            "subtitle": {"type": "string"}, "icon": {"type": "string"},
            "description": {"type": "string"},
            "shape": {"type": "string"}, "task_type": {"type": "string"},
            "target": {"type": "string"}, "count": {"type": "integer"},
        }, ("quest_id",)),
        spec("get_quest_data", "Read all raw properties and child objects of one real quest.", {
            "quest_id": {"type": "string"},
        }, ("quest_id",)),
        spec("update_quest_fields", "Patch official quest fields without replacing tasks or rewards. Use null to restore an inherited/default field.", {
            "quest_id": {"type": "string"},
            "changes": {"type": "object", "additionalProperties": True},
        }, ("quest_id", "changes")),
        spec("get_chapter_data", "Read all raw properties, links, and images of one real chapter.", {
            "chapter_id": {"type": "string"},
        }, ("chapter_id",)),
        spec("update_chapter_fields", "Patch official chapter fields while preserving quests, links, images, and addon fields.", {
            "chapter_id": {"type": "string"},
            "changes": {"type": "object", "additionalProperties": True},
        }, ("chapter_id", "changes")),
        spec("add_chapter_object", "Add a chapter image or cross-chapter quest link.", {
            "chapter_id": {"type": "string"}, "kind": {"type": "string", "enum": ["image", "link"]},
            "values": {"type": "object", "additionalProperties": True},
        }, ("chapter_id", "kind", "values")),
        spec("update_chapter_object", "Patch one chapter image or quest link by ID.", {
            "chapter_id": {"type": "string"}, "kind": {"type": "string", "enum": ["image", "link"]},
            "object_id": {"type": "string"}, "changes": {"type": "object", "additionalProperties": True},
        }, ("chapter_id", "kind", "object_id", "changes")),
        spec("remove_chapter_object", "Remove one chapter image or quest link by ID.", {
            "chapter_id": {"type": "string"}, "kind": {"type": "string", "enum": ["image", "link"]},
            "object_id": {"type": "string"},
        }, ("chapter_id", "kind", "object_id")),
        spec("get_quest_sections", "Read the complete tasks and rewards of one real quest before advanced editing.", {
            "quest_id": {"type": "string"},
        }, ("quest_id",)),
        spec("replace_quest_sections", "Replace complete task and/or reward lists after inspecting them. Changes remain undoable.", {
            "quest_id": {"type": "string"},
            "tasks": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "rewards": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        }, ("quest_id",)),
        spec("add_quest_object", "Add one typed task or reward without replacing existing objects.", {
            "quest_id": {"type": "string"}, "kind": {"type": "string", "enum": ["task", "reward"]},
            "type_id": {"type": "string"},
            "values": {"type": "object", "additionalProperties": True},
        }, ("quest_id", "kind", "type_id")),
        spec("add_task_condition", "Add one typed FTB Quests completion condition. Values must follow get_ftb_schema.", {
            "quest_id": {"type": "string"},
            "type_id": {"type": "string", "enum": list(FTB_TASK_TYPES)},
            "values": {"type": "object"},
        }, ("quest_id", "type_id")),
        spec("update_quest_object", "Patch fields on one task or reward while preserving all other and addon fields. Use null to remove a field.", {
            "quest_id": {"type": "string"}, "kind": {"type": "string", "enum": ["task", "reward"]},
            "object_id": {"type": "string"},
            "changes": {"type": "object", "additionalProperties": True},
        }, ("quest_id", "kind", "object_id", "changes")),
        spec("remove_quest_object", "Remove one task or reward by ID.", {
            "quest_id": {"type": "string"}, "kind": {"type": "string", "enum": ["task", "reward"]},
            "object_id": {"type": "string"},
        }, ("quest_id", "kind", "object_id")),
        spec("move_quest_object", "Reorder one task or reward in its quest.", {
            "quest_id": {"type": "string"}, "kind": {"type": "string", "enum": ["task", "reward"]},
            "object_id": {"type": "string"}, "new_index": {"type": "integer"},
        }, ("quest_id", "kind", "object_id", "new_index")),
        spec("get_book_document", "Read data.snbt, chapter_groups.snbt, or one reward_tables file.", {
            "path": {"type": "string"},
        }, ("path",)),
        spec("update_book_document", "Patch a supporting SNBT document without deleting unknown fields. Use null to remove a field.", {
            "path": {"type": "string"},
            "changes": {"type": "object", "additionalProperties": True},
        }, ("path", "changes")),
        spec("list_translations", "List combined native FTB Quests translations for one locale.", {
            "locale": {"type": "string"},
        }, ("locale",)),
        spec("update_translation", "Update or remove one native FTB Quests translation. Use null to remove it.", {
            "locale": {"type": "string"}, "object_type": {"type": "string"},
            "object_id": {"type": "string"},
            "field": {"type": "string", "enum": ["title", "quest_subtitle", "quest_desc", "chapter_subtitle"]},
            "value": {},
        }, ("locale", "object_type", "object_id", "field")),
        spec("create_reward_table", "Create an independent FTB Quests reward table.", {
            "title": {"type": "string"},
        }),
        spec("create_chapter_group", "Create one chapter group.", {
            "title": {"type": "string"},
        }),
        spec("remove_chapter_group", "Remove one chapter group and move its chapters back to the default group.", {
            "group_id": {"type": "string"},
        }, ("group_id",)),
        spec("remove_reward_table", "Delete one reward table file transactionally. The path must come from project data.", {
            "path": {"type": "string"},
        }, ("path",)),
        spec("get_document_objects", "Read a list such as chapter_groups or reward-table rewards.", {
            "path": {"type": "string"}, "section": {"type": "string"},
        }, ("path", "section")),
        spec("add_document_object", "Add one chapter group or reward-table child while preserving the document.", {
            "path": {"type": "string"}, "section": {"type": "string"},
            "values": {"type": "object", "additionalProperties": True},
        }, ("path", "section", "values")),
        spec("update_document_object", "Patch one chapter group or reward-table child by ID.", {
            "path": {"type": "string"}, "section": {"type": "string"}, "object_id": {"type": "string"},
            "changes": {"type": "object", "additionalProperties": True},
        }, ("path", "section", "object_id", "changes")),
        spec("remove_document_object", "Remove one chapter group or reward-table child by ID.", {
            "path": {"type": "string"}, "section": {"type": "string"}, "object_id": {"type": "string"},
        }, ("path", "section", "object_id")),
        spec("move_document_object", "Reorder one chapter group or reward-table child.", {
            "path": {"type": "string"}, "section": {"type": "string"}, "object_id": {"type": "string"},
            "new_index": {"type": "integer"},
        }, ("path", "section", "object_id", "new_index")),
        spec("move_quest", "Move a quest to exact FTB canvas coordinates.", {
            "quest_id": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"},
        }, ("quest_id", "x", "y")),
        spec("move_quest_to_chapter", "Move one existing quest to another chapter without changing its ID or child objects.", {
            "quest_id": {"type": "string"}, "chapter_id": {"type": "string"},
            "x": {"type": "number"}, "y": {"type": "number"},
        }, ("quest_id", "chapter_id")),
        spec("copy_quest", "Copy a quest with fresh quest/task/reward IDs while preserving lossless fields and translations.", {
            "quest_id": {"type": "string"}, "chapter_id": {"type": "string"},
            "x": {"type": "number"}, "y": {"type": "number"},
            "with_dependencies": {"type": "boolean"},
        }, ("quest_id", "chapter_id", "x", "y")),
        spec("copy_chapter_object", "Copy a chapter image or quest link with a fresh ID.", {
            "source_chapter_id": {"type": "string"}, "target_chapter_id": {"type": "string"},
            "kind": {"type": "string", "enum": ["image", "link"]}, "object_id": {"type": "string"},
            "x": {"type": "number"}, "y": {"type": "number"},
        }, ("source_chapter_id", "target_chapter_id", "kind", "object_id", "x", "y")),
        spec("connect_quests", "Make a quest depend on another quest.", {
            "quest_id": {"type": "string"}, "dependency_id": {"type": "string"},
        }, ("quest_id", "dependency_id")),
        spec("apply_dependency_plan", "Atomically apply up to 40 prerequisite edges. Use for branches and merges after reading exact quest IDs.", {
            "edges": {
                "type": "array", "minItems": 1, "maxItems": 40,
                "items": {
                    "type": "object",
                    "properties": {
                        "quest_id": {"type": "string"},
                        "dependency_id": {"type": "string"},
                    },
                    "required": ["quest_id", "dependency_id"],
                },
            },
        }, ("edges",)),
        spec("disconnect_quests", "Remove one dependency from a quest.", {
            "quest_id": {"type": "string"}, "dependency_id": {"type": "string"},
        }, ("quest_id", "dependency_id")),
        spec("remove_quest", "Remove one quest. This is undoable until the app closes.", {
            "quest_id": {"type": "string"},
        }, ("quest_id",)),
        spec("search_items", "Search real item IDs scanned from this modpack. Use namespace with an empty query and limit=100 to browse a mod broadly before targeted searches.", {
            "namespace": {"type": "string"}, "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        }, ("query",)),
        spec("search_registry", "Search dimensions, entities, biomes, structures, advancements, fluids, stats, or tags without guessing IDs.", {
            "registry": {"type": "string", "enum": [
                "dimension", "entity", "entity_tag", "biome", "structure",
                "advancement", "fluid", "fluid_tag", "stat",
            ]},
            "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        }, ("registry",)),
        spec("get_recipe", "Read recipe inputs for an exact item ID.", {
            "item_id": {"type": "string"}, "depth": {"type": "integer"},
        }, ("item_id",)),
        spec("validate_project", "Validate IDs, dependencies and duplicate titles.", {}),
    ]
