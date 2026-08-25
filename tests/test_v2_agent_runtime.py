import unittest

from autoftbq_v2.agent_core.runtime import AgentReview, AgentRuntimeState, interrupted_run_message


class FakeAgent:
    has_pending_changes = True
    checkpoint_count = 2
    run_plan = type("Plan", (), {"phase": "completed"})()

    @staticmethod
    def acceptance_summary():
        return "通过"

    @staticmethod
    def transaction_summary():
        return "add_quest ×2"


class AgentRuntimeTests(unittest.TestCase):
    def test_queue_is_bounded_and_fifo_for_retained_entries(self):
        state = AgentRuntimeState(queue_limit=2)
        state.enqueue("first")
        state.enqueue("second")
        state.enqueue("third")

        self.assertEqual(state.queue, ["second", "third"])
        self.assertEqual(state.take_next(), "second")

    def test_worker_attachment_owns_busy_state(self):
        state = AgentRuntimeState()
        worker = object()
        state.attach(worker)
        self.assertTrue(state.busy)
        self.assertIs(state.detach(), worker)
        self.assertFalse(state.busy)

    def test_review_and_interruption_messages_are_ui_independent(self):
        agent = FakeAgent()
        review = AgentReview.from_agent(agent)
        retained, message = interrupted_run_message(agent, "断线", "agent.log")

        self.assertTrue(review.accepted)
        self.assertEqual(review.checkpoint_count, 2)
        self.assertTrue(retained)
        self.assertIn("继续", message)
        self.assertIn("agent.log", message)


if __name__ == "__main__":
    unittest.main()
