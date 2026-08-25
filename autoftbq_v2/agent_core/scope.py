"""Authorization policy for Agent tool calls within the selected editor scope."""

from __future__ import annotations


class AgentScopePolicy:
    """Keep intent and selection constraints separate from Agent orchestration."""

    def __init__(self, store, read_only_tools) -> None:
        self.store = store
        self.read_only_tools = frozenset(read_only_tools)

    def violation(self, name: str, arguments: dict, context: dict | None) -> str:
        if name in self.read_only_tools:
            return ""
        scope = dict(context or {})
        intent = str(scope.get("intent") or "auto")
        if intent in {"inspect", "explain"}:
            return f"{intent} 模式为只读，不能调用修改工具 {name}"
        if intent == "improve" and name in {
            "create_chapter", "add_quest", "add_quest_chain", "copy_quest",
            "create_reward_table", "create_chapter_group",
        }:
            return "改进模式默认不新增对象；如需补充内容请使用 /补全 或 /生成"

        intent_tools = {
            "layout": {"move_quest", "update_quest_fields", "update_chapter_object"},
            "connect": {
                "connect_quests", "disconnect_quests", "apply_dependency_plan",
                "update_quest_fields",
            },
            "polish": {
                "update_quest", "update_quest_fields", "update_chapter_fields",
                "update_translation",
            },
        }
        allowed_for_intent = intent_tools.get(intent)
        if allowed_for_intent is not None and name not in allowed_for_intent:
            return f"{intent} 模式不允许调用 {name}"
        field_error = self._field_violation(intent, name, arguments)
        if field_error:
            return field_error
        if not scope.get("strict"):
            return ""
        return self._strict_violation(name, arguments, scope)

    @staticmethod
    def _field_violation(intent: str, name: str, arguments: dict) -> str:
        if intent == "polish":
            allowed_fields = {"title", "subtitle", "description"}
            if name == "update_quest":
                extra = set(arguments) - {"quest_id"} - allowed_fields
                if extra:
                    return "润色模式只能修改标题、副标题和描述"
            if name in {"update_quest_fields", "update_chapter_fields"}:
                changes = arguments.get("changes", {})
                if not isinstance(changes, dict) or set(changes) - allowed_fields:
                    return "润色模式只能修改标题、副标题和描述"
        if intent == "layout" and name == "update_quest_fields":
            changes = arguments.get("changes", {})
            allowed = {
                "x", "y", "dep_control_pts", "hide_dependency_lines",
                "hide_dependent_lines",
            }
            if not isinstance(changes, dict) or set(changes) - allowed:
                return "重排模式只能修改坐标与连线显示字段"
        if intent == "connect" and name == "update_quest_fields":
            changes = arguments.get("changes", {})
            allowed = {
                "dep_control_pts", "hide_dependency_lines", "hide_dependent_lines",
            }
            if not isinstance(changes, dict) or set(changes) - allowed:
                return "连线模式只能修改依赖和连线显示字段"
        return ""

    def _strict_violation(self, name: str, arguments: dict, scope: dict) -> str:
        chapter_ids = {str(value) for value in scope.get("chapter_ids", [])}
        quest_ids = {str(value) for value in scope.get("quest_ids", [])}
        creation_chapter_ids = {
            str(value) for value in scope.get("creation_chapter_ids", [])
        } | chapter_ids

        def quest_allowed(quest_id) -> bool:
            quest_id = str(quest_id or "")
            if quest_id in quest_ids:
                return True
            found = self.store.quest(quest_id)
            return bool(found and found[0].id in chapter_ids)

        def chapter_allowed(chapter_id) -> bool:
            return str(chapter_id or "") in chapter_ids

        quest_tools = {
            "update_quest", "update_quest_fields", "get_quest_data", "get_quest_sections",
            "replace_quest_sections", "add_quest_object", "add_task_condition",
            "update_quest_object", "remove_quest_object", "move_quest_object",
            "move_quest", "remove_quest",
        }
        chapter_tools = {
            "remove_chapter", "move_chapter", "update_chapter_fields",
            "add_chapter_object", "update_chapter_object", "remove_chapter_object",
        }
        if name in quest_tools and not quest_allowed(arguments.get("quest_id")):
            return "目标任务不在用户选择的 Agent 上下文中"
        if name in chapter_tools and not chapter_allowed(arguments.get("chapter_id")):
            return "目标章节不在用户选择的 Agent 上下文中"
        if name in {"add_quest", "add_quest_chain"}:
            if str(arguments.get("chapter_id") or "") not in creation_chapter_ids:
                return "不能在用户选择范围之外新增任务"
        if name == "create_chapter":
            return "已锁定 Agent 上下文，不能新建范围外章节"
        if name == "move_quest_to_chapter":
            if not quest_allowed(arguments.get("quest_id")):
                return "只能移动用户选择范围内的任务"
            if str(arguments.get("chapter_id") or "") not in creation_chapter_ids:
                return "不能将任务移动到选择范围外的章节"
        if name == "copy_quest":
            if not quest_allowed(arguments.get("quest_id")):
                return "只能复制用户选择范围内的任务"
            if str(arguments.get("chapter_id") or "") not in creation_chapter_ids:
                return "不能复制到选择范围外的章节"
        if name == "copy_chapter_object":
            if not chapter_allowed(arguments.get("source_chapter_id")):
                return "只能复制用户选择章节中的画布对象"
            if not chapter_allowed(arguments.get("target_chapter_id")):
                return "不能复制到选择范围外的章节"
        if name in {"connect_quests", "disconnect_quests"}:
            if not all(
                quest_allowed(arguments.get(key))
                for key in ("quest_id", "dependency_id")
            ):
                return "连线两端都必须位于用户选择的 Agent 上下文中"
        if name == "apply_dependency_plan":
            edges = arguments.get("edges", [])
            if not isinstance(edges, list) or not edges or any(
                not isinstance(edge, dict)
                or not quest_allowed(edge.get("quest_id"))
                or not quest_allowed(edge.get("dependency_id"))
                for edge in edges
            ):
                return "依赖方案包含用户选择范围外的任务"
        if name == "update_translation":
            object_type = str(arguments.get("object_type") or "")
            object_id = arguments.get("object_id")
            if object_type == "quest" and not quest_allowed(object_id):
                return "只能修改用户选择任务的翻译"
            if object_type == "chapter" and not chapter_allowed(object_id):
                return "只能修改用户选择章节的翻译"
            if object_type not in {"quest", "chapter"}:
                return "当前 Agent 上下文不允许修改该全局翻译对象"
        if name in {
            "update_book_document", "create_reward_table", "create_chapter_group",
            "remove_chapter_group", "remove_reward_table", "add_document_object",
            "update_document_object", "remove_document_object", "move_document_object",
        }:
            return "当前 Agent 上下文不允许修改任务书全局对象"

        recognized_scoped_writes = quest_tools | chapter_tools | {
            "add_quest", "add_quest_chain", "create_chapter", "move_quest_to_chapter",
            "copy_quest", "copy_chapter_object", "connect_quests", "disconnect_quests",
            "apply_dependency_plan", "update_translation", "update_book_document",
            "create_reward_table", "create_chapter_group", "remove_chapter_group",
            "remove_reward_table", "add_document_object", "update_document_object",
            "remove_document_object", "move_document_object",
        }
        if name not in recognized_scoped_writes:
            return f"当前 Agent 上下文尚未授权修改工具 {name}"
        return ""
