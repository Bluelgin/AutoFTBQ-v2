import unittest

from autoftbq_v2.agent_core.session import AgentSessionService


class FakeAgent:
    def __init__(self, store, client, toolbox, asset_index=None):
        self.store = store
        self.client = client
        self.toolbox = toolbox
        self.asset_index = asset_index
        self.history = []
        self.request_context = {}
        self.imported = None
        self.prepared = ""

    def import_run_state(self, value):
        self.imported = value

    def export_run_state(self):
        return {"phase": "executing"}

    def set_request_context(self, value):
        self.request_context = dict(value)

    def prepare_run(self, value):
        self.prepared = value


class AgentSessionServiceTests(unittest.TestCase):
    def test_prepare_restores_new_agent_and_builds_worker(self):
        service = AgentSessionService(
            agent_factory=FakeAgent,
            worker_factory=lambda agent, prompt: (agent, prompt),
        )
        prepared = service.prepare(
            current_agent=None, store="store", client_factory=lambda: "client",
            toolbox="tools", asset_index="assets", structured_prompt="request",
            request_context={"intent": "generate"},
            restored_history=[{"role": "user", "content": "old"}],
            restored_run_state={"phase": "paused"},
        )

        self.assertEqual(prepared.agent.history[0]["content"], "old")
        self.assertEqual(prepared.agent.imported, {"phase": "paused"})
        self.assertEqual(prepared.agent.prepared, "request")
        self.assertEqual(prepared.worker[1], "request")

    def test_existing_agent_does_not_recreate_client(self):
        agent = FakeAgent(None, None, None)
        service = AgentSessionService(agent_factory=FakeAgent, worker_factory=lambda *_: "worker")
        prepared = service.prepare(
            current_agent=agent, store=None,
            client_factory=lambda: self.fail("client should not be recreated"),
            toolbox=None, asset_index=None, structured_prompt="继续",
            request_context={"intent": "auto"},
        )
        self.assertIs(prepared.agent, agent)

    def test_capture_returns_restartable_state(self):
        agent = FakeAgent(None, None, None)
        agent.history = [{"role": "assistant", "content": "ok"}]
        agent.request_context = {"intent": "inspect"}

        state = AgentSessionService.capture(agent)

        self.assertEqual(state.run_state["phase"], "executing")
        self.assertEqual(state.request_context["intent"], "inspect")


if __name__ == "__main__":
    unittest.main()
