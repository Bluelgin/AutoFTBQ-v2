"""Transaction and safe-checkpoint management for Agent edits."""

from __future__ import annotations

from collections import Counter
from typing import Callable


class AgentTransactionManager:
    """Keep Agent writes recoverable without coupling them to model orchestration."""

    def __init__(self, store, max_checkpoints: int = 16, on_checkpoint: Callable | None = None):
        self.store = store
        self.max_checkpoints = max(1, int(max_checkpoints))
        self.on_checkpoint = on_checkpoint
        self.original_snapshot = None
        self.baseline_errors: set[tuple[str, str]] = set()
        self.actions: list[str] = []
        self.failure = ""
        self.checkpoints: list[dict] = []
        self.rejections: dict[str, str] = {}
        self.serial = 0

    @property
    def active(self) -> bool:
        return self.original_snapshot is not None

    @property
    def has_pending_changes(self) -> bool:
        return self.active and bool(self.actions)

    @property
    def checkpoint_count(self) -> int:
        return max(0, len(self.checkpoints) - 1)

    def begin(self, baseline_errors: set[tuple[str, str]], resume: bool = False) -> bool:
        """Start a transaction, returning False when an active run is resumed."""
        if self.active and resume:
            self.failure = ""
            return False
        if self.active:
            self.commit()
        self.original_snapshot = self.store.capture_state()
        self.baseline_errors = set(baseline_errors)
        self.actions = []
        self.failure = ""
        self.rejections = {}
        self.serial = 0
        self.checkpoints = [{
            "label": "开始本轮任务",
            "snapshot": self.capture_step_state(),
            "action_count": 0,
            "errors": set(self.baseline_errors),
            "rejections": {},
        }]
        return True

    def capture_step_state(self):
        capture = getattr(self.store, "capture_checkpoint_state", None)
        return capture() if callable(capture) else self.store.capture_state()

    def restore_step_state(self, snapshot) -> None:
        restore = getattr(self.store, "restore_checkpoint_state", None)
        if callable(restore):
            restore(snapshot)
        else:
            self.store.restore_state(snapshot)

    def reject_tool(self, tool_name: str, message: str) -> None:
        self.rejections[tool_name] = str(message)

    def accept_tool(self, tool_name: str, errors: set[tuple[str, str]]) -> dict:
        self.rejections.pop(tool_name, None)
        self.actions.append(tool_name)
        self.serial += 1
        checkpoint = {
            "index": self.serial,
            "label": self.checkpoint_label(tool_name),
            "snapshot": self.capture_step_state(),
            "action_count": len(self.actions),
            "errors": set(errors),
            "rejections": dict(self.rejections),
        }
        self.checkpoints.append(checkpoint)
        if len(self.checkpoints) > self.max_checkpoints + 1:
            self.checkpoints.pop(1)
        if self.on_checkpoint:
            self.on_checkpoint(tool_name, checkpoint)
        return checkpoint

    def restore_latest(self) -> bool:
        if not self.checkpoints:
            return False
        target = self.checkpoints[-1]
        self.restore_step_state(target["snapshot"])
        self.actions = self.actions[: int(target["action_count"])]
        self.failure = ""
        self.rejections = dict(target.get("rejections", {}))
        return True

    def rollback_last(self) -> bool:
        if len(self.checkpoints) <= 1:
            return False
        self.checkpoints.pop()
        return self.restore_latest()

    def commit(self) -> bool:
        changed = self.has_pending_changes
        self.clear()
        return changed

    def rollback_all(self) -> bool:
        changed = self.has_pending_changes
        if self.active:
            self.store.restore_state(self.original_snapshot)
        self.clear()
        return changed

    def clear(self) -> None:
        self.original_snapshot = None
        self.baseline_errors = set()
        self.actions = []
        self.failure = ""
        self.checkpoints = []
        self.rejections = {}
        self.serial = 0

    def summary(self) -> str:
        return "、".join(f"{name} ×{count}" for name, count in Counter(self.actions).items())

    def checkpoint_summary(self) -> list[dict]:
        return [
            {
                "index": int(value.get("index", index)),
                "label": str(value.get("label") or "安全检查点"),
                "action_count": int(value.get("action_count", 0)),
            }
            for index, value in enumerate(self.checkpoints[1:], 1)
        ]

    @staticmethod
    def checkpoint_label(tool_name: str) -> str:
        return {
            "create_chapter": "已创建章节",
            "add_quest": "已添加任务",
            "add_quest_chain": "已完成一组任务",
            "apply_dependency_plan": "已完成一组连线",
            "connect_quests": "已连接任务",
            "replace_quest_sections": "已更新任务条件与奖励",
            "add_quest_object": "已添加任务条件或奖励",
            "update_quest_object": "已更新任务条件或奖励",
            "move_quest": "已调整任务位置",
            "update_quest": "已更新任务",
            "update_quest_fields": "已更新任务属性",
        }.get(tool_name, f"已完成 {tool_name}")
