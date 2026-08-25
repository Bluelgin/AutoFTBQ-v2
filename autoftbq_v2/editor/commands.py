"""Application commands used by the editor UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class CanvasPasteResult:
    kind: str
    object_id: str


class EditorProjectCommands:
    """Coordinate existing store operations without depending on Qt widgets."""

    def __init__(self, store_provider: Callable[[], object]) -> None:
        self._store_provider = store_provider

    @property
    def store(self):
        return self._store_provider()

    def create_chapter(self):
        title = f"新章节 {len(self.store.project.chapters) + 1}"
        return self.store.create_chapter(title)

    def move_chapter(self, chapter_id: str, current_index: int, delta: int, count: int) -> bool:
        if current_index < 0 or not chapter_id or count < 1:
            return False
        target = max(0, min(current_index + delta, count - 1))
        if target == current_index:
            return False
        self.store.move_chapter(chapter_id, target)
        return True

    def add_quest(self, chapter_id: str, x: float, y: float):
        chapter = self.store.chapter(chapter_id)
        ordinal = len(chapter.quests) + 1 if chapter else 1
        quest = self.store.add_quest(chapter_id, f"新任务 {ordinal}", "", "checkmark")
        self.store.move_quest(quest.id, x, y)
        return quest

    def paste_canvas_object(
        self,
        source: dict,
        target_chapter_id: str,
        x: float,
        y: float,
        *,
        as_link: bool = False,
        with_dependencies: bool = True,
    ) -> CanvasPasteResult:
        kind = str(source.get("kind") or "")
        object_id = str(source.get("id") or "")
        source_chapter_id = str(source.get("chapter_id") or "")
        if not kind or not object_id:
            raise ValueError("画布剪贴板内容无效")
        if kind == "quest" and as_link:
            value = self.store.add_chapter_object(target_chapter_id, "link", {
                "linked_quest": object_id,
                "x": x,
                "y": y,
                "shape": "circle",
                "size": 1.0,
            })
            return CanvasPasteResult("link", value["id"])
        if kind == "quest":
            quest = self.store.copy_quest(
                object_id,
                target_chapter_id,
                x,
                y,
                with_dependencies=with_dependencies,
            )
            return CanvasPasteResult("quest", quest.id)
        if not hasattr(self.store, "copy_chapter_object"):
            raise ValueError("当前项目格式不包含章节图片或跳转数据")
        value = self.store.copy_chapter_object(
            source_chapter_id, kind, object_id, target_chapter_id, x, y,
        )
        return CanvasPasteResult(kind, value["id"])

    def remove_canvas_objects(self, chapter_id: str, references: list[tuple[str, str]]) -> None:
        if hasattr(self.store, "remove_canvas_objects"):
            self.store.remove_canvas_objects(chapter_id, references)
            return
        for kind, object_id in references:
            if kind == "quest":
                self.store.remove_quest(object_id)

    def update_quest_basics(self, quest_id: str, changes: dict) -> None:
        self.store.update_quest(quest_id, **changes)

    def move_quest(self, quest_id: str, x: float, y: float):
        return self.store.move_quest(quest_id, x, y)

    def move_quest_to_chapter(self, quest_id: str, chapter_id: str):
        return self.store.move_quest_to_chapter(quest_id, chapter_id)

    def remove_quest(self, quest_id: str) -> bool:
        return self.store.remove_quest(quest_id)

    def remove_chapter(self, chapter_id: str) -> bool:
        return self.store.remove_chapter(chapter_id)

    def update_quest_fields(self, quest_id: str, changes: dict):
        return self.store.update_quest_fields(quest_id, changes)

    def update_chapter_fields(self, chapter_id: str, changes: dict):
        return self.store.update_chapter_fields(chapter_id, changes)

    def update_chapter_object(
        self, chapter_id: str, kind: str, object_id: str, changes: dict,
    ):
        return self.store.update_chapter_object(chapter_id, kind, object_id, changes)

    def update_document(self, relative_path: str, changes: dict):
        return self.store.update_document(relative_path, changes)
