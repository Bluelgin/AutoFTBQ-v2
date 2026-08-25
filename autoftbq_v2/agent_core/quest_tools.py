"""Core chapter and quest write-tool handlers."""

from __future__ import annotations

from dataclasses import dataclass

from ..ftb.schema import TASK_TYPES


@dataclass(frozen=True)
class QuestToolResult:
    handled: bool
    value: object = None


class AgentQuestTools:
    """Translate core Agent commands into existing ProjectStore operations."""

    def __init__(self, store):
        self.store = store

    def execute(self, name: str, arguments: dict) -> QuestToolResult:
        handler = getattr(self, f"_handle_{name}", None)
        if not callable(handler):
            return QuestToolResult(False)
        return QuestToolResult(True, handler(arguments))

    def _handle_create_chapter(self, arguments: dict):
        chapter = self.store.create_chapter(
            arguments.get("title", ""), arguments.get("icon", "minecraft:book"),
        )
        return {"chapter_id": chapter.id, "title": chapter.title}

    def _handle_remove_chapter(self, arguments: dict):
        return {"removed": self.store.remove_chapter(arguments.get("chapter_id", ""))}

    def _handle_move_chapter(self, arguments: dict):
        chapters = self.store.move_chapter(arguments.get("chapter_id", ""), arguments.get("new_index", 0))
        return [{"chapter_id": chapter.id, "title": chapter.title} for chapter in chapters]

    def _handle_add_quest(self, arguments: dict):
        quest = self.store.add_quest(
            arguments.get("chapter_id", ""), arguments.get("title", ""),
            arguments.get("description", ""), arguments.get("task_type", "checkmark"),
            arguments.get("target", ""), arguments.get("count", 1),
        )
        return {"quest_id": quest.id, "title": quest.title}

    def _handle_add_quest_chain(self, arguments: dict):
        chapter_id = str(arguments.get("chapter_id", ""))
        chapter = self.store.chapter(chapter_id)
        values = arguments.get("quests", [])
        if chapter is None:
            return {"error": "章节不存在"}
        if not isinstance(values, list) or not 1 <= len(values) <= 12:
            return {"error": "任务链必须包含 1 至 12 个任务"}
        if any(not isinstance(value, dict) for value in values):
            return {"error": "任务链条目必须是对象"}
        for value in values:
            task_type = str(value.get("task_type", "checkmark"))
            if task_type not in TASK_TYPES:
                return {"error": f"不支持的任务类型：{task_type}"}
            if not str(value.get("title", "")).strip():
                return {"error": "任务链中的标题不能为空"}
        snapshot = self.store.capture_state()
        created = []
        previous_id = str(arguments.get("start_dependency_id", "") or "")
        row_width = max(2, min(int(arguments.get("row_width", 5) or 5), 8))
        base_index = len(chapter.quests)
        try:
            for offset, value in enumerate(values):
                quest = self.store.add_quest(
                    chapter_id, str(value.get("title", "")), str(value.get("description", "")),
                    str(value.get("task_type", "checkmark")), str(value.get("target", "")),
                    int(value.get("count", 1) or 1),
                )
                visual_index = base_index + offset
                self.store.move_quest(
                    quest.id, float((visual_index % row_width) * 3),
                    float((visual_index // row_width) * 2.2),
                )
                if previous_id:
                    self.store.connect(quest.id, previous_id)
                previous_id = quest.id
                created.append({
                    "quest_id": quest.id, "title": quest.title,
                    "dependencies": list(quest.dependencies), "x": quest.x, "y": quest.y,
                })
            return {"chapter_id": chapter_id, "created": created}
        except Exception:
            self.store.restore_state(snapshot)
            raise

    def _handle_update_quest(self, arguments: dict):
        changes = {key: value for key, value in arguments.items() if key != "quest_id"}
        quest = self.store.update_quest(arguments.get("quest_id", ""), **changes)
        return {"quest_id": quest.id, "title": quest.title}

    def _handle_move_quest(self, arguments: dict):
        quest = self.store.move_quest(
            arguments.get("quest_id", ""), arguments.get("x", 0), arguments.get("y", 0),
        )
        return {"quest_id": quest.id, "x": quest.x, "y": quest.y}

    def _handle_move_quest_to_chapter(self, arguments: dict):
        quest = self.store.move_quest_to_chapter(
            arguments.get("quest_id", ""), arguments.get("chapter_id", ""),
            arguments.get("x"), arguments.get("y"),
        )
        return {
            "quest_id": quest.id, "chapter_id": arguments.get("chapter_id", ""),
            "x": quest.x, "y": quest.y,
        }

    def _handle_copy_quest(self, arguments: dict):
        quest = self.store.copy_quest(
            arguments.get("quest_id", ""), arguments.get("chapter_id", ""),
            arguments.get("x", 0), arguments.get("y", 0),
            arguments.get("with_dependencies", True),
        )
        return {
            "quest_id": quest.id, "chapter_id": arguments.get("chapter_id", ""),
            "x": quest.x, "y": quest.y,
        }

    def _handle_connect_quests(self, arguments: dict):
        quest = self.store.connect(arguments.get("quest_id", ""), arguments.get("dependency_id", ""))
        return {"quest_id": quest.id, "dependencies": quest.dependencies}

    def _handle_apply_dependency_plan(self, arguments: dict):
        edges = arguments.get("edges", [])
        if not isinstance(edges, list) or not 1 <= len(edges) <= 40:
            return {"error": "依赖方案必须包含 1 至 40 条连线"}
        if any(not isinstance(edge, dict) for edge in edges):
            return {"error": "每条依赖必须是对象"}
        snapshot = self.store.capture_state()
        applied = []
        try:
            for edge in edges:
                quest_id = str(edge.get("quest_id", ""))
                dependency_id = str(edge.get("dependency_id", ""))
                quest = self.store.connect(quest_id, dependency_id)
                applied.append({
                    "quest_id": quest.id, "dependency_id": dependency_id,
                    "dependencies": list(quest.dependencies),
                })
            return {"applied": applied}
        except Exception:
            self.store.restore_state(snapshot)
            raise

    def _handle_disconnect_quests(self, arguments: dict):
        quest = self.store.disconnect(arguments.get("quest_id", ""), arguments.get("dependency_id", ""))
        return {"quest_id": quest.id, "dependencies": quest.dependencies}

    def _handle_remove_quest(self, arguments: dict):
        return {"removed": self.store.remove_quest(arguments.get("quest_id", ""))}
