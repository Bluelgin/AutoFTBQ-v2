"""Application orchestration for preparing and restoring Agent runs."""

from __future__ import annotations

from dataclasses import dataclass

from ..agent import ProjectAgent
from ..infrastructure.workers import AgentWorker


@dataclass(frozen=True)
class PreparedAgentRun:
    agent: ProjectAgent
    worker: object


@dataclass(frozen=True)
class PersistedAgentState:
    history: list[dict]
    run_state: dict
    request_context: dict


class AgentSessionService:
    def __init__(self, agent_factory=ProjectAgent, worker_factory=AgentWorker):
        self.agent_factory = agent_factory
        self.worker_factory = worker_factory

    def prepare(
        self,
        *,
        current_agent,
        store,
        client_factory,
        toolbox,
        asset_index,
        structured_prompt: str,
        request_context: dict,
        restored_history=(),
        restored_run_state: dict | None = None,
    ) -> PreparedAgentRun:
        agent = current_agent
        if agent is None:
            agent = self.agent_factory(
                store, client_factory(), toolbox, asset_index=asset_index,
            )
            agent.history = [dict(value) for value in restored_history]
            agent.import_run_state(restored_run_state or {})
        agent.set_request_context(request_context)
        agent.prepare_run(structured_prompt)
        return PreparedAgentRun(agent, self.worker_factory(agent, structured_prompt))

    @staticmethod
    def capture(agent) -> PersistedAgentState:
        if agent is None:
            return PersistedAgentState([], {}, {})
        return PersistedAgentState(
            history=list(agent.history),
            run_state=agent.export_run_state(),
            request_context=dict(agent.request_context),
        )
