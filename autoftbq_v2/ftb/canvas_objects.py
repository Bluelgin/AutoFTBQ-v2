"""Chapter canvas object mutations for real FTB Quests stores."""

from __future__ import annotations

from copy import deepcopy


class FTBCanvasObjectEditor:
    """Edit chapter images and quest links while preserving raw compounds."""

    SECTIONS = {"image": "images", "link": "quest_links"}

    def __init__(self, store, new_id) -> None:
        self.store = store
        self.new_id = new_id

    def copy(
        self,
        source_chapter_id: str,
        kind: str,
        object_id: str,
        target_chapter_id: str,
        x: float,
        y: float,
    ) -> dict:
        section = self.SECTIONS.get(kind)
        if section is None or self.store.chapter(target_chapter_id) is None:
            raise ValueError("复制对象类型或目标章节无效")
        source = self.store.raw_chapters.get(source_chapter_id, {}).get(section, [])
        value = next(
            (
                deepcopy(raw)
                for raw in source
                if isinstance(raw, dict) and str(raw.get("id")) == str(object_id)
            ),
            None,
        )
        if value is None:
            raise ValueError(f"找不到{kind}：{object_id}")
        old_id = str(value.get("id") or "")
        value["id"] = self.new_id()
        value["x"] = float(x)
        value["y"] = float(y)
        self.store._checkpoint()
        raw_target = self.store.raw_chapters.setdefault(target_chapter_id, {})
        raw_target.setdefault(section, []).append(value)
        self.store.dirty_chapters.add(target_chapter_id)
        self.store._copy_translation_ids({old_id: value["id"]} if old_id else {})
        return deepcopy(value)

    def add(self, chapter_id: str, kind: str, values: dict) -> dict:
        section = self.SECTIONS.get(kind)
        if section is None or not isinstance(values, dict):
            raise ValueError("章节对象必须是 image 或 link")
        if self.store.chapter(chapter_id) is None:
            raise ValueError(f"找不到章节：{chapter_id}")
        self.store._checkpoint()
        raw = self.store.raw_chapters.setdefault(chapter_id, {})
        objects = raw.setdefault(section, [])
        if not isinstance(objects, list):
            objects = []
            raw[section] = objects
        value = {"id": self.new_id(), **deepcopy(values)}
        objects.append(value)
        self.store.dirty_chapters.add(chapter_id)
        return deepcopy(value)

    def update(
        self, chapter_id: str, kind: str, object_id: str, changes: dict,
    ) -> dict:
        section = self.SECTIONS.get(kind)
        if section is None or not isinstance(changes, dict):
            raise ValueError("无效的章节对象修改")
        raw = self.store.raw_chapters.get(chapter_id, {})
        objects = raw.get(section, [])
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
        self.store.dirty_chapters.add(chapter_id)
        return deepcopy(target)

    def remove(self, chapter_id: str, kind: str, object_id: str) -> bool:
        section = self.SECTIONS.get(kind)
        if section is None:
            raise ValueError("章节对象必须是 image 或 link")
        raw = self.store.raw_chapters.get(chapter_id, {})
        objects = raw.get(section, [])
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
        self.store.dirty_chapters.add(chapter_id)
        self.store._remove_translation_ids({str(object_id)})
        return True

    def remove_many(self, chapter_id: str, references: list[tuple[str, str]]) -> int:
        valid = []
        raw = self.store.raw_chapters.get(chapter_id, {})
        for kind, object_id in references:
            if kind == "quest" and self.store.quest(object_id):
                valid.append((kind, object_id))
            elif kind in self.SECTIONS:
                section = self.SECTIONS[kind]
                if any(
                    isinstance(value, dict) and str(value.get("id")) == str(object_id)
                    for value in raw.get(section, [])
                ):
                    valid.append((kind, object_id))
        if not valid:
            return 0
        undo_start = len(self.store._undo)
        for kind, object_id in valid:
            if kind == "quest":
                self.store.remove_quest(object_id)
            else:
                self.remove(chapter_id, kind, object_id)
        initial = self.store._undo[undo_start]
        self.store._undo = self.store._undo[:undo_start] + [initial]
        return len(valid)
