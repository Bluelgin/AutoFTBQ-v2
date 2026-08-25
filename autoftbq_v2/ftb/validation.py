"""Whole-book structural validation for lossless FTB Quests documents."""

from __future__ import annotations

import os
from typing import Any

from .schema import CURRENT_FILE_VERSION, REWARD_TYPES, TASK_TYPES


TASK_REQUIRED = {
    "item": (("item",),),
    "xp": (("value",),),
    "dimension": (("dimension",),),
    "stat": (("stat",), ("value",)),
    "kill": (("entity", "entityTypeTag"), ("value",)),
    "location": (("position",), ("size",)),
    "advancement": (("advancement",),),
    "observation": (("to_observe",),),
    "biome": (("biome",),),
    "structure": (("structure",),),
    "gamestage": (("stage",),),
    "fluid": (("fluid",),),
}

REWARD_REQUIRED = {
    "item": (("item",),),
    "choice": (("table_id", "table_data"),),
    "all_table": (("table_id", "table_data"),),
    "random": (("table_id", "table_data"),),
    "loot": (("table_id", "table_data"),),
    "command": (("command",),),
    "xp": (("xp",),),
    "xp_levels": (("xp_levels",),),
    "advancement": (("advancement",),),
    "gamestage": (("stage",),),
    "currency": (("amount",),),
}


def _issue(severity: str, location: str, message: str) -> dict[str, str]:
    return {"severity": severity, "location": location, "message": message}


def _core_type(value: Any) -> str:
    type_id = str(value or "")
    return type_id.split(":", 1)[1] if type_id.startswith("ftbquests:") else type_id


def _has_any(raw: dict, keys: tuple[str, ...]) -> bool:
    return any(key in raw and raw[key] not in (None, "", [], {}) for key in keys)


def _validate_typed_object(raw: dict, kind: str, location: str, issues: list[dict]) -> None:
    type_id = _core_type(raw.get("type"))
    registry = TASK_TYPES if kind == "task" else REWARD_TYPES
    required = TASK_REQUIRED if kind == "task" else REWARD_REQUIRED
    if not type_id:
        issues.append(_issue("error", location, "缺少 type"))
        return
    if type_id not in registry:
        return
    for alternatives in required.get(type_id, ()):
        if not _has_any(raw, alternatives):
            issues.append(_issue("error", location, f"{type_id} 缺少字段：{' 或 '.join(alternatives)}"))


def validate_ftb_store(store, known_items: dict | None = None) -> list[dict]:
    issues: list[dict] = []
    all_ids: dict[str, str] = {}
    quest_ids: set[str] = set()
    dependency_graph: dict[str, list[str]] = {}
    reward_table_ids: set[str] = set()

    data_key = os.path.normpath("data.snbt")
    if data_key not in store.raw_documents:
        issues.append(_issue("warning", "任务书", "缺少 data.snbt，全局设置无法验证"))
    else:
        version = store.raw_documents[data_key].get("version")
        if isinstance(version, int) and version > CURRENT_FILE_VERSION:
            issues.append(_issue(
                "warning", "data.snbt",
                f"任务书格式版本 {version} 高于当前已核对版本 {CURRENT_FILE_VERSION}，将保留未知字段",
            ))

    def register(raw: dict, location: str) -> str:
        object_id = str(raw.get("id") or "")
        if not object_id:
            issues.append(_issue("error", location, "缺少对象 ID"))
        elif object_id in all_ids:
            issues.append(_issue("error", location, f"ID 与 {all_ids[object_id]} 重复：{object_id}"))
        else:
            all_ids[object_id] = location
        return object_id

    groups = store.raw_documents.get(os.path.normpath("chapter_groups.snbt"), {}).get("chapter_groups", [])
    group_ids = set()
    if isinstance(groups, list):
        for index, group in enumerate(groups):
            if isinstance(group, dict):
                group_id = register(group, f"章节分组 #{index + 1}")
                if group_id:
                    group_ids.add(group_id)

    for table in store.list_reward_tables():
        raw = table["data"]
        table_id = register(raw, table["path"])
        if table_id:
            reward_table_ids.add(table_id)
        rewards = raw.get("rewards", [])
        if not isinstance(rewards, list):
            issues.append(_issue("error", table["path"], "rewards 必须是列表"))
        else:
            for index, reward in enumerate(rewards):
                if not isinstance(reward, dict):
                    issues.append(_issue("error", table["path"], f"奖励 #{index + 1} 不是 compound"))
                    continue
                register(reward, f"{table['path']} / 奖励 #{index + 1}")
                _validate_typed_object(reward, "reward", f"{table['path']} / 奖励 #{index + 1}", issues)

    pending_references: list[tuple[str, str, str]] = []
    for chapter in store.project.chapters:
        raw_chapter = store._sync_chapter(chapter)
        register(raw_chapter, f"章节 {chapter.title}")
        group_id = str(raw_chapter.get("group") or "")
        if group_id and group_id not in group_ids:
            issues.append(_issue("error", chapter.title, f"章节分组不存在：{group_id}"))

        for section, label in (("quest_links", "跳转链接"), ("images", "章节图片")):
            values = raw_chapter.get(section, [])
            if not isinstance(values, list):
                issues.append(_issue("error", chapter.title, f"{section} 必须是列表"))
                continue
            for index, value in enumerate(values):
                location = f"{chapter.title} / {label} #{index + 1}"
                if not isinstance(value, dict):
                    issues.append(_issue("error", location, "对象不是 compound"))
                    continue
                register(value, location)
                reference = value.get("linked_quest") if section == "quest_links" else value.get("dependency")
                if reference:
                    pending_references.append((location, str(reference), "引用对象"))

        quests = raw_chapter.get("quests", [])
        if not isinstance(quests, list):
            issues.append(_issue("error", chapter.title, "quests 必须是列表"))
            continue
        for q_index, quest in enumerate(quests):
            if not isinstance(quest, dict):
                issues.append(_issue("error", chapter.title, f"任务 #{q_index + 1} 不是 compound"))
                continue
            location = f"{chapter.title} / {quest.get('title') or q_index + 1}"
            quest_id = register(quest, location)
            if quest_id:
                quest_ids.add(quest_id)
            dependencies = quest.get("dependencies", [])
            if not isinstance(dependencies, list):
                issues.append(_issue("error", location, "dependencies 必须是列表"))
                dependencies = []
            dependency_graph[quest_id] = [str(value) for value in dependencies]
            pending_references.extend((location, str(value), "前置对象") for value in dependencies)
            for section, kind, label in (("tasks", "task", "条件"), ("rewards", "reward", "奖励")):
                values = quest.get(section, [])
                if not isinstance(values, list):
                    issues.append(_issue("error", location, f"{section} 必须是列表"))
                    continue
                for index, value in enumerate(values):
                    child_location = f"{location} / {label} #{index + 1}"
                    if not isinstance(value, dict):
                        issues.append(_issue("error", child_location, "对象不是 compound"))
                        continue
                    register(value, child_location)
                    _validate_typed_object(value, kind, child_location, issues)
                    type_id = _core_type(value.get("type"))
                    if kind == "reward" and type_id in ("choice", "all_table", "random", "loot"):
                        table_id = str(value.get("table_id") or "")
                        if table_id and table_id not in reward_table_ids:
                            issues.append(_issue("error", child_location, f"奖励表不存在：{table_id}"))

    for location, reference, label in pending_references:
        if reference not in all_ids:
            issues.append(_issue("error", location, f"{label}不存在：{reference}"))

    state: dict[str, int] = {}

    def visit(quest_id: str) -> bool:
        if state.get(quest_id) == 1:
            return True
        if state.get(quest_id) == 2:
            return False
        state[quest_id] = 1
        cyclic = any(dep in quest_ids and visit(dep) for dep in dependency_graph.get(quest_id, []))
        state[quest_id] = 2
        return cyclic

    if any(visit(quest_id) for quest_id in quest_ids):
        issues.append(_issue("error", "任务书", "任务前置关系存在循环"))
    return issues
