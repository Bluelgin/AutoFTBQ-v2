"""Per-run evidence ledger for gameplay registry IDs used by the Agent."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..ftb.schema import object_spec
from ..infrastructure.asset_index import AssetIndex
from .item_policy import AgentItemPolicy


TASK_TARGET_REGISTRIES = {
    "item": "item",
    "kill": "entity",
    "dimension": "dimension",
    "advancement": "advancement",
    "biome": "biome",
    "structure": "structure",
    "fluid": "fluid",
    "stat": "stat",
}


@dataclass(frozen=True)
class RegistryReference:
    registry: str
    identifier: str


class AgentIdPolicy:
    """Validate gameplay IDs and remember which ones tools actually returned."""

    def __init__(self, store, asset_index=None, item_policy: AgentItemPolicy | None = None):
        self.store = store
        self.asset_index = asset_index
        self.item_policy = item_policy or AgentItemPolicy(store, asset_index)
        self.observed: dict[str, set[str]] = defaultdict(set)
        self.warned: set[tuple[str, str]] = set()

    def reset(self) -> None:
        self.observed.clear()
        self.warned.clear()

    @staticmethod
    def _identifier(value) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("id", "item", "fluid"):
                found = AgentIdPolicy._identifier(value.get(key))
                if found:
                    return found
        return ""

    @classmethod
    def _object_refs(cls, kind: str, value: dict) -> list[RegistryReference]:
        if not isinstance(value, dict):
            return []
        type_id = str(value.get("type", value.get("type_id", "")) or "")
        refs = []
        for field in object_spec(kind, type_id).fields:
            registry = str(field.registry or "")
            if not registry or field.key not in value:
                continue
            identifier = cls._identifier(value.get(field.key))
            if identifier:
                refs.append(RegistryReference(registry, identifier))
        if "icon" in value:
            identifier = cls._identifier(value.get("icon"))
            if identifier:
                refs.append(RegistryReference("item", identifier))
        return refs

    def _current_task_type(self, quest_id: str) -> str:
        found = self.store.quest(quest_id)
        task = found[1].tasks[0] if found and found[1].tasks else None
        return str(task.type if task else "")

    def references(self, tool_name: str, arguments: dict) -> list[RegistryReference]:
        name = str(tool_name)
        a = arguments if isinstance(arguments, dict) else {}
        refs = [RegistryReference("item", value) for value in self.item_policy.references(name, a)]

        if name == "add_quest":
            registry = TASK_TARGET_REGISTRIES.get(str(a.get("task_type", "")))
            identifier = self._identifier(a.get("target"))
            if registry and identifier:
                refs.append(RegistryReference(registry, identifier))
        elif name == "add_quest_chain":
            for quest in a.get("quests", []) if isinstance(a.get("quests"), list) else []:
                if not isinstance(quest, dict):
                    continue
                registry = TASK_TARGET_REGISTRIES.get(str(quest.get("task_type", "")))
                identifier = self._identifier(quest.get("target"))
                if registry and identifier:
                    refs.append(RegistryReference(registry, identifier))
        elif name == "update_quest" and "target" in a:
            task_type = str(a.get("task_type", "")) or self._current_task_type(a.get("quest_id", ""))
            registry = TASK_TARGET_REGISTRIES.get(task_type)
            identifier = self._identifier(a.get("target"))
            if registry and identifier:
                refs.append(RegistryReference(registry, identifier))
        elif name == "replace_quest_sections":
            for kind, key in (("task", "tasks"), ("reward", "rewards")):
                for value in a.get(key, []) if isinstance(a.get(key), list) else []:
                    refs.extend(self._object_refs(kind, value))
        elif name in {"add_quest_object", "add_task_condition"}:
            kind = "task" if name == "add_task_condition" else str(a.get("kind", ""))
            values = a.get("values", {})
            typed = {**(values if isinstance(values, dict) else {}), "type": a.get("type_id", "")}
            refs.extend(self._object_refs(kind, typed))
        elif name == "update_quest_object":
            kind = str(a.get("kind", ""))
            changes = a.get("changes", {})
            type_id = ""
            if hasattr(self.store, "raw_sections"):
                tasks, rewards = self.store.raw_sections(a.get("quest_id", ""))
                values = tasks if kind == "task" else rewards
                current = next(
                    (value for value in values if str(value.get("id", "")) == str(a.get("object_id", ""))),
                    {},
                )
                type_id = str(current.get("type", ""))
            typed = {**(changes if isinstance(changes, dict) else {}), "type": type_id}
            refs.extend(self._object_refs(kind, typed))

        unique = []
        seen = set()
        for ref in refs:
            key = (ref.registry, ref.identifier)
            if ref.identifier and key not in seen:
                seen.add(key)
                unique.append(ref)
        return unique

    def _registry_values(self, registry: str) -> dict[str, str]:
        if self.asset_index is not None and hasattr(self.asset_index, "registry_values"):
            return self.asset_index.registry_values(registry)
        return AssetIndex.builtin_registry_values(registry)

    def is_valid(self, ref: RegistryReference) -> tuple[bool, str]:
        if ref.registry == "item":
            status = self.item_policy.status(ref.identifier)
            return status.allowed, "；".join(status.reasons)
        values = self._registry_values(ref.registry)
        if ref.identifier in values:
            return True, ""
        if self.asset_index is None and not values:
            return False, "尚未扫描整合包，无法确认此类注册表 ID"
        return False, f"ID 不在已扫描的 {ref.registry} 注册表中"

    def rejection(self, tool_name: str, arguments: dict) -> dict | None:
        invalid = []
        for ref in self.references(tool_name, arguments):
            valid, reason = self.is_valid(ref)
            if not valid:
                invalid.append((ref, reason))
        if not invalid:
            return None
        ref, reason = invalid[0]
        return {
            "error": f"ID {ref.identifier} 已被注册表策略拒绝：{reason}",
            "registry": ref.registry,
            "invalid_ids": [
                {"registry": value.registry, "id": value.identifier, "reason": detail}
                for value, detail in invalid
            ],
            "recovery": "请先调用 search_items 或 search_registry 查询当前整合包，再从返回结果中选择。",
        }

    def unobserved(self, tool_name: str, arguments: dict) -> list[RegistryReference]:
        values = [
            ref for ref in self.references(tool_name, arguments)
            if ref.identifier not in self.observed.get(ref.registry, set())
            and (ref.registry, ref.identifier) not in self.warned
            and self.is_valid(ref)[0]
        ]
        self.warned.update((ref.registry, ref.identifier) for ref in values)
        return values

    def observe(self, tool_name: str, arguments: dict, result) -> None:
        name = str(tool_name)
        a = arguments if isinstance(arguments, dict) else {}
        if name == "search_items" and isinstance(result, list):
            self.observed["item"].update(
                str(value.get("item_id", "")) for value in result if isinstance(value, dict)
            )
        elif name == "search_registry" and isinstance(result, list):
            registry = str(a.get("registry", ""))
            self.observed[registry].update(
                str(value.get("id", "")) for value in result if isinstance(value, dict)
            )
        elif name == "get_recipe" and isinstance(result, dict):
            pending = [result]
            while pending:
                value = pending.pop()
                output = str(value.get("output", ""))
                if output:
                    self.observed["item"].add(output)
                self.observed["item"].update(str(item) for item in value.get("inputs", []) if item)
                pending.extend(
                    child for child in value.get("prerequisites", []) if isinstance(child, dict)
                )
