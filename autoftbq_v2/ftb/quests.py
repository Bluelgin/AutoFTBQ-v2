"""Lifecycle operations for quests backed by real FTB Quests compounds."""

from __future__ import annotations

from copy import deepcopy

from .quest_objects import task_count, task_target
from ..project import ProjectStore, Quest, Task


class FTBQuestEditor:
    """Coordinate quest domain changes with raw compounds and translations."""

    def __init__(self, store, new_id) -> None:
        self.store = store
        self.new_id = new_id

    def add(
        self,
        chapter_id: str,
        title: str,
        description: str = "",
        task_type: str = "checkmark",
        target: str = "",
        count: int = 1,
    ) -> Quest:
        chapter = self.store.chapter(chapter_id)
        if chapter is None:
            raise ValueError(f"找不到章节：{chapter_id}")
        self.store._checkpoint()
        quest = Quest(
            id=self.new_id(),
            title=title.strip() or "新任务",
            description=[description.strip()] if description.strip() else [],
            tasks=[Task(task_type or "checkmark", target.strip(), max(1, int(count or 1)))],
            x=float(len(chapter.quests) * 2.5),
            y=0.0,
        )
        chapter.quests.append(quest)
        self.store.raw_quests[quest.id] = self.store._sync_quest(quest)
        self.store.dirty_chapters.add(chapter_id)
        return quest

    def update(self, quest_id: str, **changes) -> Quest:
        found = self.store.quest(quest_id)
        if found is None:
            raise ValueError(f"找不到任务：{quest_id}")
        self.store._checkpoint()
        quest = found[1]
        if "title" in changes:
            quest.title = str(changes["title"]).strip() or quest.title
        if "subtitle" in changes:
            quest.subtitle = str(changes["subtitle"]).strip()
        if "icon" in changes:
            quest.icon = str(changes["icon"]).strip()
        if "shape" in changes:
            quest.shape = str(changes["shape"]).strip()
        if "description" in changes:
            value = str(changes["description"]).strip()
            quest.description = value.splitlines() if value else []
        task = quest.tasks[0] if quest.tasks else Task()
        if "task_type" in changes:
            task.type = str(changes["task_type"]).strip() or task.type
        if "target" in changes:
            task.target = str(changes["target"]).strip()
        if "count" in changes:
            task.count = max(1, int(changes["count"] or 1))
        if not quest.tasks:
            quest.tasks.append(task)
        self.store._sync_quest(quest)
        self.store.dirty_chapters.add(found[0].id)
        return quest

    def move(self, quest_id: str, x: float, y: float) -> Quest:
        quest = ProjectStore.move_quest(self.store, quest_id, x, y)
        self.store._mark_quest(quest_id)
        return quest

    def move_to_chapter(
        self,
        quest_id: str,
        chapter_id: str,
        x: float | None = None,
        y: float | None = None,
    ) -> Quest:
        found = self.store.quest(quest_id)
        if found is None:
            raise ValueError(f"找不到任务：{quest_id}")
        source_id = found[0].id
        quest = ProjectStore.move_quest_to_chapter(
            self.store, quest_id, chapter_id, x, y,
        )
        self.store.dirty_chapters.update({source_id, chapter_id})
        return quest

    def copy(
        self,
        quest_id: str,
        chapter_id: str,
        x: float,
        y: float,
        with_dependencies: bool = True,
    ) -> Quest:
        found = self.store.quest(quest_id)
        target = self.store.chapter(chapter_id)
        if found is None or target is None:
            raise ValueError("复制来源或目标章节不存在")
        source_raw = deepcopy(self.store.raw_quests.get(quest_id, {}))
        if not source_raw:
            source_raw = self.store._sync_quest(found[1])
        self.store._checkpoint()
        id_map = {quest_id: self.new_id()}
        source_raw["id"] = id_map[quest_id]
        source_raw["title"] = f"{source_raw.get('title') or found[1].title} 副本"
        source_raw["x"] = float(x)
        source_raw["y"] = float(y)
        if not with_dependencies:
            source_raw["dependencies"] = []
        for section in ("tasks", "rewards"):
            children = source_raw.get(section, [])
            for child in children if isinstance(children, list) else []:
                if isinstance(child, dict):
                    old_id = str(child.get("id") or "")
                    new_id_value = self.new_id()
                    child["id"] = new_id_value
                    if old_id:
                        id_map[old_id] = new_id_value
        temporary = self.store._chapter_from_raw(
            {"id": chapter_id, "title": target.title, "quests": [source_raw]},
            f"{chapter_id}.snbt",
        )
        quest = temporary.quests[0]
        target.quests.append(quest)
        self.store.raw_quests[quest.id] = source_raw
        target_raw = self.store.raw_chapters.setdefault(chapter_id, {})
        target_raw.setdefault("quests", []).append(source_raw)
        self.store.dirty_chapters.add(chapter_id)
        self.store._copy_translation_ids(id_map)
        return quest

    def connect(self, quest_id: str, dependency_id: str) -> Quest:
        found = self.store.quest(quest_id)
        dependency = self.store.quest(dependency_id)
        if found is None or dependency is None:
            raise ValueError("依赖任务不存在")
        if dependency_id == quest_id:
            raise ValueError("任务不能依赖自身")
        if self.store._depends_on(dependency_id, quest_id):
            raise ValueError("这条连线会形成循环依赖")
        if dependency_id not in found[1].dependencies:
            self.store._checkpoint()
            found[1].dependencies.append(dependency_id)
            self.store.dirty_chapters.add(found[0].id)
        return found[1]

    def disconnect(self, quest_id: str, dependency_id: str) -> Quest:
        quest = ProjectStore.disconnect(self.store, quest_id, dependency_id)
        self.store._mark_quest(quest_id)
        return quest

    def remove(self, quest_id: str) -> bool:
        found = self.store.quest(quest_id)
        if found is None:
            return False
        raw = self.store.raw_quests.get(quest_id, {})
        removed_objects = {quest_id}
        for section in ("tasks", "rewards"):
            removed_objects.update(
                str(value.get("id"))
                for value in raw.get(section, [])
                if isinstance(value, dict) and value.get("id")
            )
        chapter_id = found[0].id
        removed = ProjectStore.remove_quest(self.store, quest_id)
        self.store.raw_quests.pop(quest_id, None)
        self.store.dirty_chapters.add(chapter_id)
        self.store._remove_translation_ids(removed_objects)
        return removed

    def replace_sections(self, quest_id: str, tasks, rewards) -> Quest:
        found = self.store.quest(quest_id)
        if found is None:
            raise ValueError(f"找不到任务：{quest_id}")
        if not isinstance(tasks, list) or not all(isinstance(value, dict) for value in tasks):
            raise ValueError("任务 SNBT 必须是 compound 列表")
        if not isinstance(rewards, list) or not all(isinstance(value, dict) for value in rewards):
            raise ValueError("奖励 SNBT 必须是 compound 列表")
        self.store._checkpoint()
        quest = found[1]
        quest.tasks = [
            Task(
                str(raw.get("type") or "checkmark"),
                task_target(raw),
                task_count(raw),
            )
            for raw in tasks
        ] or [Task()]
        quest.rewards = deepcopy(rewards)
        raw = self.store.raw_quests.setdefault(quest_id, {})
        raw["tasks"] = deepcopy(tasks)
        raw["rewards"] = deepcopy(rewards)
        self.store.dirty_chapters.add(found[0].id)
        return quest
