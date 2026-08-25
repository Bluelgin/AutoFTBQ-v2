"""Application-level orchestration for two-click quest connections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ConnectionResult:
    status: str
    message: str
    source_id: str = ""
    target_id: str = ""

    @property
    def connected(self) -> bool:
        return self.status == "connected"


class QuestConnectionController:
    """Own connection gesture state while the store owns dependency rules."""

    def __init__(self, store_provider: Callable[[], object]) -> None:
        self._store_provider = store_provider
        self.source_id = ""
        self.busy = False

    @property
    def store(self):
        return self._store_provider()

    def reset(self) -> None:
        self.source_id = ""

    def click(self, quest_id: str) -> ConnectionResult:
        if self.busy:
            return ConnectionResult("busy", "正在保存上一条连线，请稍候")
        quest_id = str(quest_id or "")
        selected = self.store.quest(quest_id)
        if not self.source_id:
            if selected is None:
                return ConnectionResult("rejected", "任务已经不存在，请重新选择前置任务")
            self.source_id = quest_id
            return ConnectionResult(
                "selected",
                f"前置：{selected[1].title}，再点击后置任务 B",
                source_id=quest_id,
            )

        source_id = self.source_id
        self.source_id = ""
        if source_id == quest_id:
            return ConnectionResult("rejected", "不能连接任务自身，请重新选择 A")
        source = self.store.quest(source_id)
        target = selected or self.store.quest(quest_id)
        if source is None or target is None:
            return ConnectionResult("rejected", "任务已经不存在，请重新选择前置任务")
        if source_id in target[1].dependencies:
            return ConnectionResult("rejected", "这两个任务已经连接，无需重复添加")

        self.busy = True
        try:
            self.store.connect(quest_id, source_id)
            return ConnectionResult(
                "connected",
                f"已连接 A -> {target[1].title}，可继续选择下一组",
                source_id=source_id,
                target_id=quest_id,
            )
        except ValueError as exc:
            return ConnectionResult("rejected", str(exc))
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            return ConnectionResult("error", f"无法连接：{message}")
        finally:
            self.busy = False
