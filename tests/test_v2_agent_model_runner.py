import json
import unittest

from autoftbq_v2.agent_core.model_runner import AgentModelRunner


class Registry:
    @staticmethod
    def specs(names=None):
        specs = [{"type": "function", "function": {"name": "inspect"}}]
        return [spec for spec in specs if names is None or spec["function"]["name"] in names]

    @staticmethod
    def function_specs(names=None):
        specs = [{"name": "inspect"}]
        return [spec for spec in specs if names is None or spec["name"] in names]


class NativeClient:
    def chat_with_tools(self, messages, specs, handler, **kwargs):
        self.received = (messages, specs, handler, kwargs)
        return "原生完成", {"usage": 1}


class AdaptiveClient(NativeClient):
    def __init__(self):
        self.reasoning_effort = "low"

    def chat_with_tools(self, messages, specs, handler, **kwargs):
        self.seen_effort = self.reasoning_effort
        return super().chat_with_tools(messages, specs, handler, **kwargs)


class FallbackClient:
    def __init__(self):
        self.calls = 0

    def chat(self, _messages, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return json.dumps({"actions": [{"tool": "inspect", "arguments": {}}]}), {}
        return json.dumps({"actions": [], "reply": "回退完成"}), {}


class AgentModelRunnerTests(unittest.TestCase):
    def test_shared_fallback_retains_trace_for_game_continuation(self):
        trace = []
        runner = AgentModelRunner(FallbackClient(), Registry, lambda *_: '{"ok":true}')
        answer, truncated = runner.invoke_with_specs([], Registry.specs(), trace_sink=trace)
        self.assertEqual(answer, "回退完成")
        self.assertFalse(truncated)
        self.assertEqual(trace[0]["result"], {"ok": True})

    def test_fallback_cannot_execute_tool_outside_selected_adapter(self):
        calls = []
        runner = AgentModelRunner(FallbackClient(), Registry, lambda *args: calls.append(args))
        answer, truncated = runner.invoke_with_specs([], [])
        self.assertFalse(calls)
        self.assertFalse(truncated)

    def test_native_tool_client_receives_unchanged_limits(self):
        client = NativeClient()
        runner = AgentModelRunner(client, Registry, lambda *_: "{}")

        result = runner.invoke([{"role": "user", "content": "test"}], 7)

        self.assertEqual(result, "原生完成")
        self.assertEqual(client.received[3]["max_rounds"], 7)
        self.assertEqual(client.received[3]["max_tokens"], 4096)

    def test_native_tool_client_receives_only_selected_tools(self):
        client = NativeClient()
        runner = AgentModelRunner(client, Registry, lambda *_: "{}")

        runner.invoke([{"role": "user", "content": "test"}], 7, {"missing"})

        self.assertEqual(client.received[1], [])

    def test_repair_temporarily_escalates_reasoning_without_changing_saved_setting(self):
        client = AdaptiveClient()
        runner = AgentModelRunner(client, Registry, lambda *_: "{}")

        runner.invoke(
            [{"role": "user", "content": "test"}], 7,
            minimum_reasoning_effort="medium",
        )

        self.assertEqual(client.seen_effort, "medium")
        self.assertEqual(client.reasoning_effort, "low")

    def test_action_envelope_accepts_markdown_json_fence(self):
        envelope = AgentModelRunner.action_envelope(
            '```json\n{"actions":[],"reply":"ok"}\n```',
        )
        self.assertEqual(envelope["reply"], "ok")

    def test_fallback_protocol_executes_actions_and_returns_reply(self):
        calls = []
        client = FallbackClient()
        runner = AgentModelRunner(
            client, Registry,
            lambda name, arguments: calls.append((name, arguments)) or '{"ok":true}',
        )

        result = runner.invoke([{"role": "user", "content": "test"}], 5)

        self.assertEqual(result, "回退完成")
        self.assertEqual(calls, [("inspect", {})])
        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
