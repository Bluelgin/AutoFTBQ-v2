"""Read-only tool handlers for inspecting an editable quest project."""

from __future__ import annotations

from dataclasses import dataclass

from ..infrastructure.asset_index import AssetIndex
from ..ftb.schema import object_spec, schema_catalog
from .item_policy import AgentItemPolicy


@dataclass(frozen=True)
class QueryToolResult:
    handled: bool
    value: object = None


class AgentQueryTools:
    """Execute inspection tools without knowing about Agent transactions."""

    def __init__(self, store, toolbox, skills, asset_index=None):
        self.store = store
        self.toolbox = toolbox
        self.skills = skills
        self.asset_index = asset_index

    def execute(self, name: str, arguments: dict) -> QueryToolResult:
        handler = getattr(self, f"_handle_{name}", None)
        if not callable(handler):
            return QueryToolResult(False)
        return QueryToolResult(True, handler(arguments))

    def _handle_get_project_summary(self, _arguments: dict):
        return self.store.summary()

    def _handle_get_chapter_quests(self, arguments: dict):
        chapter = self.store.chapter(arguments.get("chapter_id", ""))
        if chapter is None:
            return {"error": "章节不存在"}
        return [
            {
                "quest_id": quest.id, "title": quest.title, "x": quest.x, "y": quest.y,
                "shape": quest.shape, "dependencies": quest.dependencies,
                "tasks": [
                    {"type": task.type, "target": task.target, "count": task.count}
                    for task in quest.tasks
                ],
            }
            for quest in chapter.quests
        ]

    def _handle_get_ftb_schema(self, arguments: dict):
        kind = str(arguments.get("kind", "all") or "all")
        type_id = str(arguments.get("type_id", "") or "")
        catalog = schema_catalog()
        if kind in ("task", "reward") and type_id:
            spec_value = object_spec(kind, type_id)
            return {
                "kind": kind, "type": spec_value.type_id, "label": spec_value.label,
                "fields": [field.__dict__ for field in spec_value.fields],
            }
        if kind in ("task", "reward"):
            return catalog[f"{kind}s"]
        if kind in ("quest", "chapter", "book"):
            return catalog[f"{kind}_fields"]
        return catalog

    def _handle_list_skills(self, _arguments: dict):
        return self.skills.catalog()

    def _handle_load_skill(self, arguments: dict):
        return self.skills.load(arguments.get("skill_id", ""))

    def _handle_get_quest_data(self, arguments: dict):
        if not hasattr(self.store, "quest_data"):
            return {"error": "请先打开真实 FTB Quests 任务书"}
        return self.store.quest_data(arguments.get("quest_id", ""))

    def _handle_get_chapter_data(self, arguments: dict):
        if not hasattr(self.store, "chapter_data"):
            return {"error": "请先打开真实 FTB Quests 任务书"}
        return self.store.chapter_data(arguments.get("chapter_id", ""))

    def _handle_get_quest_sections(self, arguments: dict):
        quest_id = arguments.get("quest_id", "")
        if hasattr(self.store, "raw_sections"):
            tasks, rewards = self.store.raw_sections(quest_id)
            return {"quest_id": quest_id, "tasks": tasks, "rewards": rewards}
        found = self.store.quest(quest_id)
        if found is None:
            return {"error": "任务不存在"}
        return {
            "quest_id": quest_id,
            "tasks": [task.__dict__ for task in found[1].tasks],
            "rewards": found[1].rewards,
        }

    def _handle_get_book_document(self, arguments: dict):
        if not hasattr(self.store, "document"):
            return {"error": "请先打开真实 FTB Quests 任务书"}
        return self.store.document(arguments.get("path", ""))

    def _handle_list_translations(self, arguments: dict):
        if not hasattr(self.store, "translation_entries"):
            return {"error": "请先打开真实 FTB Quests 任务书"}
        return self.store.translation_entries(arguments.get("locale", ""))

    def _handle_get_document_objects(self, arguments: dict):
        if not hasattr(self.store, "document_objects"):
            return {"error": "请先打开真实 FTB Quests 任务书"}
        return self.store.document_objects(arguments.get("path", ""), arguments.get("section", ""))

    def _handle_search_items(self, arguments: dict):
        return self.toolbox.search_items(
            arguments.get("namespace", ""), arguments.get("query", ""), arguments.get("limit", 20),
        )

    def _handle_search_registry(self, arguments: dict):
        registry = str(arguments.get("registry", ""))
        query = str(arguments.get("query", ""))
        limit = max(1, min(int(arguments.get("limit", 20) or 20), 50))
        if self.asset_index and hasattr(self.asset_index, "search_registry"):
            matches = self.asset_index.search_registry(registry, query, limit)
        else:
            values = AssetIndex.builtin_registry_values(registry)
            needle = query.casefold().strip()
            matches = [
                (identifier, label) for identifier, label in values.items()
                if not needle or needle in identifier.casefold() or needle in str(label).casefold()
            ][:limit]
        return [{"id": identifier, "name": label} for identifier, label in matches]

    def _handle_get_recipe(self, arguments: dict):
        return self.toolbox.get_recipe(arguments.get("item_id", ""), arguments.get("depth", 1))

    def _handle_validate_project(self, _arguments: dict):
        issues = list(self.store.validate(self.toolbox.all_items))
        if self.asset_index is not None:
            issues.extend(AgentItemPolicy(self.store, self.asset_index).existing_warnings())
        return issues
