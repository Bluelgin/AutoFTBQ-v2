"""Translation document commands for FTB Quests books."""

from __future__ import annotations

from copy import deepcopy
import os
import re


class FTBTranslationEditor:
    def __init__(self, host, path_resolver):
        self.host = host
        self.path_resolver = path_resolver

    def locales(self) -> list[str]:
        prefix = os.path.normpath("lang") + os.sep
        locales = {
            path[len(prefix):].split(os.sep, 1)[0]
            for path in self.host.raw_documents
            if path.startswith(prefix) and os.sep in path[len(prefix):]
        }
        return sorted(locale for locale in locales if re.fullmatch(r"\w+", locale))

    def entries(self, locale: str) -> dict:
        locale = self._locale(locale)
        prefix = os.path.normpath(os.path.join("lang", locale)) + os.sep
        combined = {}
        for path in sorted(self.host.raw_documents):
            if path.startswith(prefix):
                combined.update(deepcopy(self.host.raw_documents[path]))
        return combined

    def update(self, locale: str, object_type: str, object_id: str, field: str, value) -> dict:
        locale = self._locale(locale)
        object_type = str(object_type or "").strip()
        object_id = str(object_id or "").strip()
        field = str(field or "").strip()
        if field not in {"title", "quest_subtitle", "quest_desc", "chapter_subtitle"}:
            raise ValueError(f"不支持的翻译字段：{field}")
        if not object_type or not object_id:
            raise ValueError("翻译对象类型和 ID 不能为空")
        key = f"{object_type}.{object_id}.{field}"
        list_field = field in {"quest_desc", "chapter_subtitle"}
        if value is not None and list_field and not isinstance(value, list):
            raise ValueError(f"{field} 必须是字符串列表")
        if value is not None and not list_field and not isinstance(value, str):
            raise ValueError(f"{field} 必须是字符串")
        prefix = os.path.normpath(os.path.join("lang", locale)) + os.sep
        path = next(
            (
                candidate for candidate, raw in self.host.raw_documents.items()
                if candidate.startswith(prefix) and key in raw
            ),
            self.path_resolver(locale, object_type, object_id),
        )
        self.host._checkpoint()
        raw = self.host.raw_documents.setdefault(path, {})
        if value is None or value == "" or value == []:
            raw.pop(key, None)
        else:
            raw[key] = deepcopy(value)
        self.host.dirty_documents.add(path)
        return {"locale": locale, "path": path, "key": key, "value": deepcopy(raw.get(key))}

    def remove_object_ids(self, object_ids: set[str]) -> None:
        if not object_ids:
            return
        for path, raw in self.host.raw_documents.items():
            if not path.startswith(os.path.normpath("lang") + os.sep):
                continue
            removed = [
                key for key in raw
                if len(str(key).split(".")) >= 3 and str(key).split(".")[1] in object_ids
            ]
            for key in removed:
                raw.pop(key, None)
            if removed:
                self.host.dirty_documents.add(path)

    @staticmethod
    def _locale(value: str) -> str:
        locale = str(value or "").strip()
        if not re.fullmatch(r"\w+", locale):
            raise ValueError("语言代码只能包含字母、数字和下划线")
        return locale
