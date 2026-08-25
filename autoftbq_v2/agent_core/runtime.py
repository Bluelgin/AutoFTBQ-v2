"""Application state and outcomes for asynchronous Agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentRuntimeState:
    busy: bool = False
    worker: object | None = None
    queue: list[str] = field(default_factory=list)
    queue_limit: int = 20

    def enqueue(self, prompt: str) -> int:
        value = str(prompt or "").strip()
        if value:
            self.queue.append(value)
            self.queue = self.queue[-self.queue_limit:]
        return len(self.queue)

    def take_next(self) -> str:
        return self.queue.pop(0) if self.queue else ""

    def attach(self, worker) -> None:
        self.worker = worker
        self.busy = worker is not None

    def detach(self):
        worker = self.worker
        self.worker = None
        self.busy = False
        return worker


@dataclass(frozen=True)
class AgentReview:
    pending: bool
    accepted: bool
    heading: str
    acceptance: str
    summary: str
    checkpoint_count: int

    @classmethod
    def from_agent(cls, agent) -> "AgentReview":
        pending = bool(agent and agent.has_pending_changes)
        accepted = bool(
            agent and agent.run_plan is not None and agent.run_plan.phase == "completed"
        )
        return cls(
            pending=pending,
            accepted=accepted,
            heading=(
                "Agent 已完成计划并通过验收。"
                if accepted else "Agent 已完成本轮修改，但计划仍有缺口。"
            ),
            acceptance=agent.acceptance_summary() if agent else "",
            summary=agent.transaction_summary() if agent else "",
            checkpoint_count=agent.checkpoint_count if agent else 0,
        )


def interrupted_run_message(agent, error: str, log_path: str) -> tuple[bool, str]:
    retained = bool(agent and agent.has_pending_changes)
    suffix = (
        f"\n已保留 {agent.checkpoint_count} 个安全检查点，可以发送“继续”接着完成。"
        if retained else ""
    )
    return retained, f"{error}{suffix}\n详细日志：{log_path}"
