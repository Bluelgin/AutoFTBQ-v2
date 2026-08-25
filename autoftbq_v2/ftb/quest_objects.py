"""Loss-minimizing FTB quest task and reward object editing."""

from __future__ import annotations

from copy import deepcopy

from ..project import Quest, Task


def task_target(raw: dict) -> str:
    for key in (
        "item", "entity", "dimension", "advancement", "biome", "structure", "fluid",
        "stat", "stage", "to_observe",
    ):
        value = raw.get(key)
        if isinstance(value, dict):
            value = value.get("id") or value.get("fluid") or value.get("item")
        if value not in (None, ""):
            return str(value)
    return ""


def target_key(task_type: str) -> str | None:
    return {
        "item": "item",
        "kill": "entity",
        "dimension": "dimension",
        "advancement": "advancement",
        "biome": "biome",
        "structure": "structure",
        "fluid": "fluid",
        "stat": "stat",
        "gamestage": "stage",
        "observation": "to_observe",
    }.get(task_type)


def count_key(task_type: str) -> str | None:
    if task_type == "item":
        return "count"
    if task_type in ("kill", "stat", "xp"):
        return "value"
    return None


def task_count(raw: dict) -> int:
    key = count_key(str(raw.get("type") or ""))
    value = raw.get(key, 1) if key else 1
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def refresh_quest_sections(quest: Quest, raw: dict) -> None:
    tasks = raw.get("tasks", []) if isinstance(raw.get("tasks"), list) else []
    quest.tasks = [
        Task(str(item.get("type") or "checkmark"), task_target(item), task_count(item))
        for item in tasks
        if isinstance(item, dict)
    ]
    rewards = raw.get("rewards", [])
    quest.rewards = deepcopy(rewards) if isinstance(rewards, list) else []


def sync_task(task: Task, raw: dict, new_id) -> dict:
    raw = deepcopy(raw) if isinstance(raw, dict) else {}
    raw.setdefault("id", new_id())
    old_type = str(raw.get("type") or "")
    raw["type"] = task.type
    key = target_key(task.type)
    if old_type and old_type != task.type:
        for candidate in (
            "item", "entity", "dimension", "advancement", "biome", "structure", "fluid",
            "stat", "stage", "to_observe",
        ):
            if candidate != key:
                raw.pop(candidate, None)
        for candidate in ("count", "value"):
            if candidate != count_key(task.type):
                raw.pop(candidate, None)
    if key and task.target:
        existing = raw.get(key)
        if isinstance(existing, dict):
            existing["id"] = task.target
        else:
            raw[key] = task.target
    quantity_key = count_key(task.type)
    if quantity_key and (task.count > 1 or quantity_key in raw):
        raw[quantity_key] = task.count
    return raw


class FTBQuestObjectEditor:
    """Edit task/reward compounds and keep the lightweight quest view synchronized."""

    def __init__(self, store, new_id) -> None:
        self.store = store
        self.new_id = new_id

    @staticmethod
    def _section(kind: str) -> str:
        if kind not in ("task", "reward"):
            raise ValueError("对象类型必须是 task 或 reward")
        return "tasks" if kind == "task" else "rewards"

    def add(
        self, quest_id: str, kind: str, type_id: str, values: dict | None = None,
    ) -> dict:
        section = self._section(kind)
        found = self.store.quest(quest_id)
        if found is None:
            raise ValueError(f"找不到任务：{quest_id}")
        self.store._checkpoint()
        raw_quest = self.store.raw_quests.setdefault(quest_id, {})
        objects = raw_quest.setdefault(section, [])
        if not isinstance(objects, list):
            objects = []
            raw_quest[section] = objects
        value = {
            "id": self.new_id(),
            "type": str(type_id or ("checkmark" if kind == "task" else "item")),
        }
        if values:
            value.update(deepcopy(values))
        objects.append(value)
        refresh_quest_sections(found[1], raw_quest)
        self.store.dirty_chapters.add(found[0].id)
        return deepcopy(value)

    def update(
        self, quest_id: str, kind: str, object_id: str, changes: dict,
    ) -> dict:
        if kind not in ("task", "reward") or not isinstance(changes, dict):
            raise ValueError("无效的任务或奖励修改")
        section = self._section(kind)
        found = self.store.quest(quest_id)
        if found is None:
            raise ValueError(f"找不到任务：{quest_id}")
        raw_quest = self.store.raw_quests.setdefault(quest_id, {})
        objects = raw_quest.get(section, [])
        target = next(
            (
                obj for obj in objects
                if isinstance(obj, dict) and str(obj.get("id")) == str(object_id)
            ),
            None,
        )
        if target is None:
            raise ValueError(f"找不到{kind}：{object_id}")
        self.store._checkpoint()
        for field, value in changes.items():
            if field == "id":
                continue
            if value is None:
                target.pop(str(field), None)
            else:
                target[str(field)] = deepcopy(value)
        refresh_quest_sections(found[1], raw_quest)
        self.store.dirty_chapters.add(found[0].id)
        return deepcopy(target)

    def remove(self, quest_id: str, kind: str, object_id: str) -> bool:
        section = self._section(kind)
        found = self.store.quest(quest_id)
        if found is None:
            return False
        raw_quest = self.store.raw_quests.setdefault(quest_id, {})
        objects = raw_quest.get(section, [])
        index = next(
            (
                i for i, obj in enumerate(objects)
                if isinstance(obj, dict) and str(obj.get("id")) == str(object_id)
            ),
            -1,
        )
        if index < 0:
            return False
        self.store._checkpoint()
        objects.pop(index)
        refresh_quest_sections(found[1], raw_quest)
        self.store.dirty_chapters.add(found[0].id)
        self.store._remove_translation_ids({str(object_id)})
        return True

    def move(
        self, quest_id: str, kind: str, object_id: str, new_index: int,
    ) -> list[dict]:
        section = self._section(kind)
        found = self.store.quest(quest_id)
        if found is None:
            raise ValueError(f"找不到任务：{quest_id}")
        raw_quest = self.store.raw_quests.setdefault(quest_id, {})
        objects = raw_quest.get(section, [])
        old_index = next(
            (
                i for i, obj in enumerate(objects)
                if isinstance(obj, dict) and str(obj.get("id")) == str(object_id)
            ),
            -1,
        )
        if old_index < 0:
            raise ValueError(f"找不到{kind}：{object_id}")
        self.store._checkpoint()
        value = objects.pop(old_index)
        objects.insert(max(0, min(int(new_index), len(objects))), value)
        refresh_quest_sections(found[1], raw_quest)
        self.store.dirty_chapters.add(found[0].id)
        return deepcopy(objects)
