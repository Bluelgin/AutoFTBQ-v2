"""Agent write-tool handlers for full FTB Quests projects."""

from __future__ import annotations

from dataclasses import dataclass

from ..ftb.schema import TASK_TYPE_DEFAULTS, TASK_TYPES


@dataclass(frozen=True)
class FTBToolResult:
    handled: bool
    value: object = None


class AgentFTBTools:
    def __init__(self, store):
        self.store = store

    def execute(self, name: str, args: dict) -> FTBToolResult:
        handler = getattr(self, f"_handle_{name}", None)
        return FTBToolResult(False) if not callable(handler) else FTBToolResult(True, handler(args))

    def _missing(self, method: str):
        return None if hasattr(self.store, method) else {"error": "请先打开真实 FTB Quests 任务书"}

    def _handle_update_quest_fields(self, a):
        return self._missing("update_quest_fields") or self.store.update_quest_fields(a.get("quest_id", ""), a.get("changes", {}))

    def _handle_update_chapter_fields(self, a):
        return self._missing("update_chapter_fields") or self.store.update_chapter_fields(a.get("chapter_id", ""), a.get("changes", {}))

    def _handle_add_chapter_object(self, a):
        return self._missing("add_chapter_object") or self.store.add_chapter_object(a.get("chapter_id", ""), a.get("kind", ""), a.get("values", {}))

    def _handle_update_chapter_object(self, a):
        return self._missing("update_chapter_object") or self.store.update_chapter_object(a.get("chapter_id", ""), a.get("kind", ""), a.get("object_id", ""), a.get("changes", {}))

    def _handle_remove_chapter_object(self, a):
        error = self._missing("remove_chapter_object")
        return error or {"removed": self.store.remove_chapter_object(a.get("chapter_id", ""), a.get("kind", ""), a.get("object_id", ""))}

    def _handle_replace_quest_sections(self, a):
        error = self._missing("replace_quest_sections")
        if error:
            return error
        quest_id = a.get("quest_id", "")
        old_tasks, old_rewards = self.store.raw_sections(quest_id)
        quest = self.store.replace_quest_sections(quest_id, a.get("tasks", old_tasks), a.get("rewards", old_rewards))
        return {"quest_id": quest.id, "tasks": len(quest.tasks), "rewards": len(quest.rewards)}

    def _handle_add_quest_object(self, a):
        return self._missing("add_quest_object") or self.store.add_quest_object(a.get("quest_id", ""), a.get("kind", ""), a.get("type_id", ""), a.get("values", {}))

    def _handle_add_task_condition(self, a):
        type_id = str(a.get("type_id", ""))
        if type_id not in TASK_TYPES:
            return {"error": f"不支持的官方条件类型：{type_id}"}
        if not hasattr(self.store, "add_quest_object"):
            return {"error": "当前项目不支持完整任务条件"}
        supplied = a.get("values", {})
        values = {**TASK_TYPE_DEFAULTS.get(type_id, {}), **(supplied if isinstance(supplied, dict) else {})}
        return self.store.add_quest_object(a.get("quest_id", ""), "task", type_id, values)

    def _quest_object(self, method, a, final):
        error = self._missing(method)
        if error:
            return error
        args = [a.get("quest_id", ""), a.get("kind", ""), a.get("object_id", ""), final]
        return getattr(self.store, method)(*args)

    def _handle_update_quest_object(self, a):
        return self._quest_object("update_quest_object", a, a.get("changes", {}))

    def _handle_remove_quest_object(self, a):
        error = self._missing("remove_quest_object")
        return error or {"removed": self.store.remove_quest_object(a.get("quest_id", ""), a.get("kind", ""), a.get("object_id", ""))}

    def _handle_move_quest_object(self, a):
        return self._quest_object("move_quest_object", a, a.get("new_index", 0))

    def _handle_update_book_document(self, a):
        return self._missing("update_document") or self.store.update_document(a.get("path", ""), a.get("changes", {}))

    def _handle_update_translation(self, a):
        return self._missing("update_translation") or self.store.update_translation(a.get("locale", ""), a.get("object_type", ""), a.get("object_id", ""), a.get("field", ""), a.get("value"))

    def _handle_create_reward_table(self, a):
        return self._missing("create_reward_table") or self.store.create_reward_table(a.get("title", "新奖励表"))

    def _handle_create_chapter_group(self, a):
        return self._missing("create_chapter_group") or self.store.create_chapter_group(a.get("title", "新章节分组"))

    def _handle_remove_chapter_group(self, a):
        error = self._missing("remove_chapter_group")
        return error or {"removed": self.store.remove_chapter_group(a.get("group_id", ""))}

    def _handle_remove_reward_table(self, a):
        path = str(a.get("path", ""))
        if not hasattr(self.store, "remove_document"):
            return {"error": "请先打开真实 FTB Quests 任务书"}
        if not path.replace("\\", "/").startswith("reward_tables/"):
            return {"error": "只能通过此工具删除 reward_tables 目录中的文件"}
        return {"removed": self.store.remove_document(path)}

    def _document_object(self, method, a, final):
        error = self._missing(method)
        if error:
            return error
        return getattr(self.store, method)(a.get("path", ""), a.get("section", ""), a.get("object_id", ""), final)

    def _handle_add_document_object(self, a):
        return self._missing("add_document_object") or self.store.add_document_object(a.get("path", ""), a.get("section", ""), a.get("values", {}))

    def _handle_update_document_object(self, a):
        return self._document_object("update_document_object", a, a.get("changes", {}))

    def _handle_remove_document_object(self, a):
        error = self._missing("remove_document_object")
        return error or {"removed": self.store.remove_document_object(a.get("path", ""), a.get("section", ""), a.get("object_id", ""))}

    def _handle_move_document_object(self, a):
        return self._document_object("move_document_object", a, a.get("new_index", 0))

    def _handle_copy_chapter_object(self, a):
        return self._missing("copy_chapter_object") or self.store.copy_chapter_object(a.get("source_chapter_id", ""), a.get("kind", ""), a.get("object_id", ""), a.get("target_chapter_id", ""), a.get("x", 0), a.get("y", 0))
