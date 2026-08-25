"""Supporting-document domain commands for an FTB Quests book."""

from __future__ import annotations

from copy import deepcopy


class FTBDocumentEditor:
    def __init__(self, host, key_factory, id_factory):
        self.host = host
        self.key = key_factory
        self.new_id = id_factory

    def document(self, relative_path: str) -> dict:
        return deepcopy(self.host.raw_documents.get(self.key(relative_path), {}))

    def update(self, relative_path: str, changes: dict) -> dict:
        if not isinstance(changes, dict):
            raise ValueError("文档修改必须是 compound")
        key = self.key(relative_path)
        self.host._checkpoint()
        raw = self.host.raw_documents.setdefault(key, {})
        self.host.deleted_documents.discard(key)
        for field, value in changes.items():
            if value is None:
                raw.pop(str(field), None)
            else:
                raw[str(field)] = deepcopy(value)
        self.host.dirty_documents.add(key)
        return deepcopy(raw)

    def replace(self, relative_path: str, value: dict) -> dict:
        if not isinstance(value, dict):
            raise ValueError("文档根节点必须是 compound")
        key = self.key(relative_path)
        self.host._checkpoint()
        self.host.raw_documents[key] = deepcopy(value)
        self.host.deleted_documents.discard(key)
        self.host.dirty_documents.add(key)
        return deepcopy(value)

    def remove(self, relative_path: str) -> bool:
        key = self.key(relative_path)
        if key not in self.host.raw_documents:
            return False
        self.host._checkpoint()
        self.host.raw_documents.pop(key, None)
        self.host.dirty_documents.discard(key)
        self.host.deleted_documents.add(key)
        return True

    def objects(self, relative_path: str, section: str) -> list[dict]:
        values = self.host.raw_documents.get(self.key(relative_path), {}).get(section, [])
        return deepcopy(values) if isinstance(values, list) else []

    def add_object(self, relative_path: str, section: str, values: dict) -> dict:
        if not section or not isinstance(values, dict):
            raise ValueError("文档列表对象无效")
        key = self.key(relative_path)
        self.host._checkpoint()
        raw = self.host.raw_documents.setdefault(key, {})
        objects = raw.setdefault(section, [])
        if not isinstance(objects, list):
            objects = []
            raw[section] = objects
        value = {"id": self.new_id(), **deepcopy(values)}
        objects.append(value)
        self.host.deleted_documents.discard(key)
        self.host.dirty_documents.add(key)
        return deepcopy(value)

    def update_object(self, relative_path: str, section: str, object_id: str, changes: dict) -> dict:
        if not isinstance(changes, dict):
            raise ValueError("文档对象修改必须是 compound")
        key = self.key(relative_path)
        objects = self.host.raw_documents.get(key, {}).get(section, [])
        target = next(
            (obj for obj in objects if isinstance(obj, dict) and str(obj.get("id")) == str(object_id)),
            None,
        )
        if target is None:
            raise ValueError(f"找不到文档对象：{object_id}")
        self.host._checkpoint()
        for field, value in changes.items():
            if field == "id":
                continue
            if value is None:
                target.pop(str(field), None)
            else:
                target[str(field)] = deepcopy(value)
        self.host.dirty_documents.add(key)
        return deepcopy(target)

    def remove_object(self, relative_path: str, section: str, object_id: str) -> bool:
        key = self.key(relative_path)
        objects = self.host.raw_documents.get(key, {}).get(section, [])
        index = next(
            (i for i, obj in enumerate(objects) if isinstance(obj, dict) and str(obj.get("id")) == str(object_id)),
            -1,
        )
        if index < 0:
            return False
        self.host._checkpoint()
        objects.pop(index)
        self.host.dirty_documents.add(key)
        self.host._remove_translation_ids({str(object_id)})
        return True

    def move_object(self, relative_path: str, section: str, object_id: str, new_index: int) -> list[dict]:
        key = self.key(relative_path)
        objects = self.host.raw_documents.get(key, {}).get(section, [])
        old_index = next(
            (i for i, obj in enumerate(objects) if isinstance(obj, dict) and str(obj.get("id")) == str(object_id)),
            -1,
        )
        if old_index < 0:
            raise ValueError(f"找不到文档对象：{object_id}")
        self.host._checkpoint()
        value = objects.pop(old_index)
        objects.insert(max(0, min(int(new_index), len(objects))), value)
        self.host.dirty_documents.add(key)
        return deepcopy(objects)
