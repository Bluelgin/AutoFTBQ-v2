"""Fail-closed item safety policy for Agent-authored quest content."""

from __future__ import annotations

from dataclasses import dataclass

from ..infrastructure.asset_index import AgentItemAvailability, UNSAFE_VANILLA_ITEMS


@dataclass(frozen=True)
class ItemPolicyViolation:
    item_id: str
    reasons: tuple[str, ...]


class AgentItemPolicy:
    """Extract item references from write tools and reject unsafe new values."""

    def __init__(self, store, asset_index=None):
        self.store = store
        self.asset_index = asset_index

    @staticmethod
    def _item_id(value) -> str:
        if isinstance(value, str):
            value = value.strip()
            return value if ":" in value else ""
        if isinstance(value, dict):
            for key in ("id", "item"):
                found = AgentItemPolicy._item_id(value.get(key))
                if found:
                    return found
        return ""

    @classmethod
    def _typed_object_refs(cls, value: dict) -> list[str]:
        if not isinstance(value, dict):
            return []
        type_id = str(value.get("type", value.get("type_id", "")) or "")
        refs = []
        if type_id == "item" or "item" in value:
            item_id = cls._item_id(value.get("item", value.get("target", "")))
            if item_id:
                refs.append(item_id)
        if type_id == "custom" or "icon" in value:
            item_id = cls._item_id(value.get("icon"))
            if item_id:
                refs.append(item_id)
        return refs

    def references(self, tool_name: str, arguments: dict) -> list[str]:
        name = str(tool_name)
        a = arguments if isinstance(arguments, dict) else {}
        refs: list[str] = []

        if name == "create_chapter":
            item_id = self._item_id(a.get("icon")) if "icon" in a else ""
            refs.extend([item_id] if item_id else [])
        elif name == "add_quest":
            if str(a.get("task_type", "")) == "item":
                item_id = self._item_id(a.get("target"))
                refs.extend([item_id] if item_id else [])
        elif name == "add_quest_chain":
            for quest in a.get("quests", []) if isinstance(a.get("quests"), list) else []:
                if isinstance(quest, dict) and str(quest.get("task_type", "")) == "item":
                    item_id = self._item_id(quest.get("target"))
                    refs.extend([item_id] if item_id else [])
        elif name == "update_quest":
            item_id = self._item_id(a.get("icon")) if "icon" in a else ""
            refs.extend([item_id] if item_id else [])
            if "target" in a:
                task_type = str(a.get("task_type", ""))
                if not task_type:
                    found = self.store.quest(a.get("quest_id", ""))
                    task = found[1].tasks[0] if found and found[1].tasks else None
                    task_type = task.type if task else ""
                if task_type == "item":
                    item_id = self._item_id(a.get("target"))
                    refs.extend([item_id] if item_id else [])
        elif name in {"update_quest_fields", "update_chapter_fields"}:
            changes = a.get("changes", {})
            if isinstance(changes, dict) and "icon" in changes:
                item_id = self._item_id(changes.get("icon"))
                refs.extend([item_id] if item_id else [])
        elif name == "replace_quest_sections":
            for section in ("tasks", "rewards"):
                for value in a.get(section, []) if isinstance(a.get(section), list) else []:
                    refs.extend(self._typed_object_refs(value))
        elif name in {"add_quest_object", "add_task_condition"}:
            values = a.get("values", {})
            typed = {**(values if isinstance(values, dict) else {}), "type": a.get("type_id", "")}
            refs.extend(self._typed_object_refs(typed))
        elif name == "update_quest_object":
            changes = a.get("changes", {})
            if isinstance(changes, dict):
                if "item" in changes:
                    item_id = self._item_id(changes.get("item"))
                    refs.extend([item_id] if item_id else [])
                if "icon" in changes:
                    item_id = self._item_id(changes.get("icon"))
                    refs.extend([item_id] if item_id else [])
        elif name in {"add_document_object", "update_document_object"}:
            values = a.get("values", a.get("changes", {}))
            refs.extend(self._typed_object_refs(values if isinstance(values, dict) else {}))
        elif name == "copy_quest":
            found = self.store.quest(a.get("quest_id", ""))
            if found is not None:
                quest = found[1]
                icon_id = self._item_id(getattr(quest, "icon", ""))
                refs.extend([icon_id] if icon_id else [])
                for task in getattr(quest, "tasks", []):
                    if getattr(task, "type", "") == "item":
                        item_id = self._item_id(getattr(task, "target", ""))
                        refs.extend([item_id] if item_id else [])
                for reward in getattr(quest, "rewards", []):
                    refs.extend(self._typed_object_refs(reward if isinstance(reward, dict) else {}))
                if hasattr(self.store, "raw_sections"):
                    tasks, rewards = self.store.raw_sections(quest.id)
                    for value in list(tasks) + list(rewards):
                        refs.extend(self._typed_object_refs(value))

        return list(dict.fromkeys(value for value in refs if value))

    def status(self, item_id: str) -> AgentItemAvailability:
        if self.asset_index is not None and hasattr(self.asset_index, "agent_item_status"):
            return self.asset_index.agent_item_status(item_id)
        if item_id.startswith("minecraft:") and item_id not in UNSAFE_VANILLA_ITEMS:
            return AgentItemAvailability(item_id, "allowed", True, (), ("原版稳定物品",))
        return AgentItemAvailability(
            item_id, "blocked", False,
            ("尚未扫描整合包，无法确认该模组物品可用",), (),
        )

    def violations(self, tool_name: str, arguments: dict) -> list[ItemPolicyViolation]:
        result = []
        for item_id in self.references(tool_name, arguments):
            status = self.status(item_id)
            if not status.allowed:
                result.append(ItemPolicyViolation(item_id, status.reasons))
        return result

    def rejection(self, tool_name: str, arguments: dict) -> dict | None:
        violations = self.violations(tool_name, arguments)
        if not violations:
            return None
        first = violations[0]
        reason = "；".join(first.reasons) or "未通过 Agent 物品白名单"
        return {
            "error": f"物品 {first.item_id} 已被 Agent 安全策略拒绝：{reason}",
            "unsafe_items": [
                {"item_id": value.item_id, "reasons": list(value.reasons)}
                for value in violations
            ],
            "recovery": "请重新调用 search_items，从返回的安全物品中选择；不要猜测或继续使用此 ID。",
        }

    def existing_warnings(self) -> list[dict]:
        """Report existing unsafe IDs without modifying or blocking the loaded project."""
        references: list[tuple[str, str]] = []
        for chapter in getattr(getattr(self.store, "project", None), "chapters", []):
            chapter_icon = self._item_id(getattr(chapter, "icon", ""))
            if chapter_icon:
                references.append((f"章节 {chapter.title}", chapter_icon))
            for quest in getattr(chapter, "quests", []):
                quest_icon = self._item_id(getattr(quest, "icon", ""))
                if quest_icon:
                    references.append((f"任务 {quest.title} 图标", quest_icon))
                for task in getattr(quest, "tasks", []):
                    if getattr(task, "type", "") == "item":
                        item_id = self._item_id(getattr(task, "target", ""))
                        if item_id:
                            references.append((f"任务 {quest.title} 条件", item_id))
                raw_values = []
                if hasattr(self.store, "raw_sections"):
                    tasks, rewards = self.store.raw_sections(quest.id)
                    raw_values = list(tasks) + list(rewards)
                else:
                    raw_values = list(getattr(quest, "rewards", []))
                for value in raw_values:
                    for item_id in self._typed_object_refs(value if isinstance(value, dict) else {}):
                        references.append((f"任务 {quest.title} 条件或奖励", item_id))
        warnings = []
        seen = set()
        for location, item_id in references:
            key = (location, item_id)
            if key in seen:
                continue
            seen.add(key)
            status = self.status(item_id)
            if status.allowed:
                continue
            reason = "；".join(status.reasons) or "未通过 Agent 物品白名单"
            warnings.append({
                "severity": "warning",
                "location": location,
                "message": f"物品 {item_id} 不会提供给 Agent：{reason}",
            })
        return warnings
