"""Strict authorization for operations proposed from an explicit game selection."""

from __future__ import annotations

from .protocol import ProtocolError


GLOBAL_OPERATIONS = {
    "update_book_raw", "upsert_chapter_group_raw", "delete_chapter_group",
    "upsert_reward_table_raw", "delete_reward_table", "create_chapter",
}
CHAPTER_OPERATIONS = {"upsert_chapter_raw", "delete_chapter"}
QUEST_OPERATIONS = {
    "upsert_quest_raw", "upsert_quest_object_raw", "delete_quest",
    "update_quest", "add_dependency", "add_item_task", "add_item_reward",
    "add_checkmark_task", "add_xp_task", "add_xp_reward",
    "add_xp_levels_reward",
}


def validate_game_selection_scope(context: dict, operations: list[dict]) -> None:
    """Reject writes outside explicitly Alt-selected chapters and quests."""
    selected_chapters = {
        _id(value.get("id")) for value in context.get("selected_chapters", [])
        if isinstance(value, dict) and _id(value.get("id"))
    }
    selected_quests = {
        _id(value.get("id")) for value in context.get("selected_quests", [])
        if isinstance(value, dict) and _id(value.get("id"))
    }
    if not selected_chapters and not selected_quests:
        return

    quest_chapters: dict[str, str] = {}
    allowed_quests = set(selected_quests)
    allowed_objects: set[str] = set()
    for value in context.get("selected_quests", []):
        if isinstance(value, dict):
            quest_chapters[_id(value.get("id"))] = _id(value.get("chapter_id"))
    for value in context.get("selected_chapters", []):
        if not isinstance(value, dict):
            continue
        chapter_id = _id(value.get("id"))
        for quest_id in value.get("quest_ids", []):
            key = _id(quest_id)
            if key:
                allowed_quests.add(key)
                quest_chapters[key] = chapter_id
    for detail in _quest_details(context):
        quest_id = _id(detail.get("id"))
        chapter_id = _id(detail.get("chapter_id"))
        if quest_id and chapter_id:
            quest_chapters[quest_id] = chapter_id
        for key in ("task_ids", "reward_ids"):
            allowed_objects.update(
                _id(value) for value in detail.get(key, []) if _id(value)
            )

    creation_chapters = set(selected_chapters)
    creation_chapters.update(
        chapter for quest, chapter in quest_chapters.items()
        if quest in selected_quests and chapter
    )
    temporary_quests: set[str] = set()

    for operation in operations:
        kind = str(operation.get("kind", ""))
        if kind in GLOBAL_OPERATIONS:
            raise ProtocolError(f"操作 {kind} 超出当前 Agent 选区")
        if kind in CHAPTER_OPERATIONS:
            _require(
                _id(operation.get("chapter_id")) in selected_chapters,
                kind, "章节未加入 Agent 上下文",
            )
            continue
        if kind == "create_quest":
            chapter_id = _id(operation.get("chapter_id"))
            _require(chapter_id in creation_chapters, kind, "目标章节未加入 Agent 上下文")
            temp_id = _id(operation.get("temp_id"))
            temporary_quests.add(temp_id)
            allowed_quests.add(temp_id)
            quest_chapters[temp_id] = chapter_id
            continue
        if kind == "remove_quest_object":
            _require(
                _id(operation.get("object_id")) in allowed_objects,
                kind, "任务对象不属于当前 Agent 选区",
            )
            continue
        if kind not in QUEST_OPERATIONS:
            raise ProtocolError(f"操作 {kind} 无法通过 Agent 选区校验")
        quest_id = _id(operation.get("quest_id"))
        if kind == "upsert_quest_raw" and quest_id not in allowed_quests:
            chapter_id = _id(operation.get("chapter_id"))
            _require(chapter_id in creation_chapters, kind, "任务与章节均不在 Agent 选区")
            allowed_quests.add(quest_id)
            quest_chapters[quest_id] = chapter_id
        else:
            _require(
                quest_id in allowed_quests or quest_id in temporary_quests,
                kind, "任务未加入 Agent 上下文",
            )
        if kind == "upsert_quest_raw":
            _require(
                _id(operation.get("chapter_id")) in creation_chapters,
                kind, "目标章节未加入 Agent 上下文",
            )


def _quest_details(context: dict):
    for value in context.get("selected_quest_details", []):
        if isinstance(value, dict):
            yield value
    for chapter in context.get("selected_chapter_details", []):
        if not isinstance(chapter, dict):
            continue
        for value in chapter.get("quests", []):
            if isinstance(value, dict):
                yield value


def _id(value) -> str:
    return str(value or "").strip().upper()


def _require(condition: bool, kind: str, message: str) -> None:
    if not condition:
        raise ProtocolError(f"操作 {kind} 被拒绝：{message}")
