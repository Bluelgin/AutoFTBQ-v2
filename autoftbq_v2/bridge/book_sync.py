"""Convert and diff live FTBQ snapshots without discarding unknown fields."""

from __future__ import annotations

from copy import deepcopy

from snbt_parser import parse_snbt, to_strict_snbt as to_snbt

from .protocol import ProtocolError


def snapshot_to_project_payload(envelope: dict) -> dict:
    if not isinstance(envelope, dict) or envelope.get("format") != "ftbquests-snbt-v1":
        raise ProtocolError("unsupported live task-book snapshot")
    snapshot = envelope.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ProtocolError("live task-book snapshot is missing")
    chapters = []
    for value in snapshot.get("chapters", []):
        if not isinstance(value, dict) or not isinstance(value.get("snbt"), str):
            raise ProtocolError("live chapter snapshot is invalid")
        try:
            chapter = parse_snbt(value["snbt"])
        except Exception as exc:
            raise ProtocolError("live chapter SNBT could not be parsed") from exc
        if not isinstance(chapter, dict):
            raise ProtocolError("live chapter SNBT must be a compound")
        chapter.setdefault("id", str(value.get("id", "")))
        chapter.setdefault("filename", str(value.get("filename", "")))
        chapters.append(chapter)
    documents = {}
    for value in snapshot.get("documents", []):
        if not isinstance(value, dict) or not isinstance(value.get("snbt"), str):
            continue
        path = str(value.get("path", "")).replace("\\", "/").strip("/")
        if not path or path.startswith("../"):
            raise ProtocolError("live supporting-document path is invalid")
        try:
            parsed = parse_snbt(value["snbt"])
        except Exception as exc:
            raise ProtocolError("live supporting-document SNBT could not be parsed") from exc
        if isinstance(parsed, dict):
            documents[path] = parsed
    documents.setdefault("data.snbt", {"version": 13})
    documents.setdefault("chapter_groups.snbt", {"chapter_groups": []})
    return {
        "format": "autoftbq-v2",
        "format_version": 2,
        "project": {"title": str(snapshot.get("title") or "Live FTB Quests"),
                    "mod_folder": ""},
        "documents": documents,
        "chapters": chapters,
        "live_sync": {
            "project_id": str(envelope.get("project_id", "")),
            "conversation_id": str(envelope.get("conversation_id", "")),
            "book_revision": str(envelope.get("book_revision", "")),
        },
    }


def _id(value: dict, field: str) -> str:
    result = str(value.get(field, "")).strip().upper()
    if not result or len(result) > 16 or any(c not in "0123456789ABCDEF" for c in result):
        raise ProtocolError(f"{field} is not a valid FTB Quests ID")
    return result


def _chapters(payload: dict) -> dict[str, dict]:
    result = {}
    for chapter in payload.get("chapters", []) if isinstance(payload, dict) else []:
        if isinstance(chapter, dict):
            result[_id(chapter, "id")] = chapter
    return result


def _quests(chapters: dict[str, dict]) -> tuple[dict[str, dict], dict[str, str]]:
    values, parents = {}, {}
    for chapter_id, chapter in chapters.items():
        for quest in chapter.get("quests", []) if isinstance(chapter.get("quests"), list) else []:
            if isinstance(quest, dict):
                quest_id = _id(quest, "id")
                values[quest_id] = quest
                parents[quest_id] = chapter_id
    return values, parents


def _without(value: dict, *keys: str) -> dict:
    return {str(key): deepcopy(item) for key, item in value.items() if key not in keys}


def _objects(quest: dict, section: str) -> dict[str, dict]:
    result = {}
    values = quest.get(section, [])
    for value in values if isinstance(values, list) else []:
        if isinstance(value, dict):
            result[_id(value, "id")] = value
    return result


def diff_project_payload(base: dict, desired: dict) -> list[dict]:
    """Create loss-minimizing raw transactions accepted by the game adapter."""
    old_chapters, new_chapters = _chapters(base), _chapters(desired)
    old_quests, old_parents = _quests(old_chapters)
    new_quests, new_parents = _quests(new_chapters)
    operations: list[dict] = []
    deferred_deletes: list[dict] = []

    old_documents = base.get("documents", {}) if isinstance(base, dict) else {}
    new_documents = desired.get("documents", {}) if isinstance(desired, dict) else {}
    old_documents = old_documents if isinstance(old_documents, dict) else {}
    new_documents = new_documents if isinstance(new_documents, dict) else {}
    if old_documents.get("data.snbt", {}) != new_documents.get("data.snbt", {}):
        operations.append({
            "kind": "update_book_raw",
            "data_snbt": to_snbt(new_documents.get("data.snbt", {})),
        })
    old_groups = {
        _id(value, "id"): value for value in old_documents.get(
            "chapter_groups.snbt", {}).get("chapter_groups", []) if isinstance(value, dict)
    }
    new_groups = {
        _id(value, "id"): value for value in new_documents.get(
            "chapter_groups.snbt", {}).get("chapter_groups", []) if isinstance(value, dict)
    }
    for group_id, value in new_groups.items():
        if old_groups.get(group_id) != value:
            operations.append({"kind": "upsert_chapter_group_raw",
                               "group_id": group_id, "data_snbt": to_snbt(value)})
    for group_id in old_groups.keys() - new_groups.keys():
        deferred_deletes.append({"kind": "delete_chapter_group", "group_id": group_id})

    def reward_tables(documents):
        return {
            _id(value, "id"): value
            for path, value in documents.items()
            if str(path).replace("\\", "/").startswith("reward_tables/")
            and isinstance(value, dict)
        }
    old_tables, new_tables = reward_tables(old_documents), reward_tables(new_documents)
    for table_id, value in new_tables.items():
        if old_tables.get(table_id) != value:
            operations.append({"kind": "upsert_reward_table_raw",
                               "reward_table_id": table_id, "data_snbt": to_snbt(value)})
    for table_id in old_tables.keys() - new_tables.keys():
        deferred_deletes.append({"kind": "delete_reward_table", "reward_table_id": table_id})

    for chapter_id, chapter in new_chapters.items():
        current = old_chapters.get(chapter_id)
        raw = _without(chapter, "quests")
        if current is None or _without(current, "quests") != raw:
            operations.append({
                "kind": "upsert_chapter_raw", "chapter_id": chapter_id,
                "data_snbt": to_snbt(raw),
            })

    for quest_id, quest in new_quests.items():
        current = old_quests.get(quest_id)
        raw = _without(quest, "tasks", "rewards")
        if (current is None or old_parents.get(quest_id) != new_parents[quest_id]
                or _without(current, "tasks", "rewards") != raw):
            operations.append({
                "kind": "upsert_quest_raw", "quest_id": quest_id,
                "chapter_id": new_parents[quest_id], "data_snbt": to_snbt(raw),
            })
        for section, object_kind in (("tasks", "task"), ("rewards", "reward")):
            old_objects = _objects(current or {}, section)
            new_objects = _objects(quest, section)
            for object_id, value in new_objects.items():
                if old_objects.get(object_id) != value:
                    type_id = str(value.get("type", "")).strip()
                    if not type_id:
                        raise ProtocolError(f"{object_kind} {object_id} has no type")
                    operations.append({
                        "kind": "upsert_quest_object_raw", "quest_id": quest_id,
                        "object_kind": object_kind, "object_id": object_id,
                        "type_id": type_id, "data_snbt": to_snbt(value),
                    })
            for object_id in old_objects.keys() - new_objects.keys():
                operations.append({"kind": "remove_quest_object", "object_id": object_id})

    for quest_id in old_quests.keys() - new_quests.keys():
        operations.append({"kind": "delete_quest", "quest_id": quest_id})
    for chapter_id in old_chapters.keys() - new_chapters.keys():
        operations.append({"kind": "delete_chapter", "chapter_id": chapter_id})
    operations.extend(deferred_deletes)
    if len(operations) > 1000:
        raise ProtocolError("task-book synchronization exceeds 1000 atomic operations")
    return operations
