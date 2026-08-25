"""Lifecycle operations for chapters backed by real FTB Quests compounds."""

from __future__ import annotations

import os

from ..project import Chapter, ProjectStore


class FTBChapterEditor:
    """Coordinate chapter domain changes with raw files and translations."""

    def __init__(self, store, new_id, document_key) -> None:
        self.store = store
        self.new_id = new_id
        self.document_key = document_key

    def create(self, title: str, icon: str = "minecraft:book") -> Chapter:
        self.store._checkpoint()
        chapter = Chapter(
            id=self.new_id(),
            title=title.strip() or "新章节",
            icon=icon or "minecraft:book",
        )
        raw = {
            "default_hide_dependency_lines": False,
            "default_quest_shape": "",
            "filename": chapter.id,
            "icon": chapter.icon,
            "id": chapter.id,
            "order_index": len(self.store.project.chapters),
            "quest_links": [],
            "quests": [],
            "title": chapter.title,
        }
        self.store.project.chapters.append(chapter)
        self.store.raw_chapters[chapter.id] = raw
        self.store.chapter_files[chapter.id] = os.path.join(
            self.store.quest_root, "chapters", f"{chapter.id}.snbt",
        )
        self.store.dirty_chapters.add(chapter.id)
        return chapter

    def remove(self, chapter_id: str) -> bool:
        chapter = self.store.chapter(chapter_id)
        if chapter is None:
            return False
        removed_quests = {quest.id for quest in chapter.quests}
        raw_chapter = self.store.raw_chapters.get(chapter_id, {})
        removed_objects = {chapter_id, *removed_quests}
        for raw_quest in (
            raw_chapter.get("quests", [])
            if isinstance(raw_chapter.get("quests"), list) else []
        ):
            if isinstance(raw_quest, dict):
                for section in ("tasks", "rewards"):
                    removed_objects.update(
                        str(value.get("id"))
                        for value in raw_quest.get(section, [])
                        if isinstance(value, dict) and value.get("id")
                    )
        for section in ("images", "quest_links"):
            removed_objects.update(
                str(value.get("id"))
                for value in raw_chapter.get(section, [])
                if isinstance(value, dict) and value.get("id")
            )
        chapter_path = self.store.chapter_files.get(chapter_id, "")
        if not ProjectStore.remove_chapter(self.store, chapter_id):
            return False
        self.store.raw_chapters.pop(chapter_id, None)
        self.store.chapter_files.pop(chapter_id, None)
        for quest_id in removed_quests:
            self.store.raw_quests.pop(quest_id, None)
        if chapter_path:
            relative = self.document_key(os.path.relpath(chapter_path, self.store.quest_root))
            self.store.deleted_documents.add(relative)
        self.store.dirty_chapters.discard(chapter_id)
        for index, current in enumerate(self.store.project.chapters):
            raw = self.store.raw_chapters.get(current.id, {})
            raw["order_index"] = index
            self.store.dirty_chapters.add(current.id)
            links = raw.get("quest_links", [])
            if isinstance(links, list):
                kept = [
                    link
                    for link in links
                    if not isinstance(link, dict)
                    or str(link.get("linked_quest") or "") not in removed_quests
                ]
                if len(kept) != len(links):
                    raw["quest_links"] = kept
                    self.store.dirty_chapters.add(current.id)
        self.store._remove_translation_ids(removed_objects)
        return True

    def move(self, chapter_id: str, new_index: int) -> list[Chapter]:
        chapters = ProjectStore.move_chapter(self.store, chapter_id, new_index)
        for index, chapter in enumerate(chapters):
            raw = self.store.raw_chapters.setdefault(chapter.id, {})
            if raw.get("order_index") != index:
                raw["order_index"] = index
                self.store.dirty_chapters.add(chapter.id)
        return chapters
