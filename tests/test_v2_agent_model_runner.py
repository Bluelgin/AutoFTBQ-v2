import json
import unittest

from autoftbq_v2.agent_core.model_runner import AgentModelRunner


class Registry:
    @staticmethod
    def specs():
        return [{"type": "function", "function": {"name": "inspect"}}]

    @staticmethod
    def function_specs():
        return [{"name": "inspect"}]


class NativeClient:
    def chat_with_tools(self, messages, specs, handler, **kwargs):
        self.received = (messages, specs, handler, kwargs)
        return "原生完成", {"usage": 1}


class FallbackClient:
    def __init__(self):
        self.calls = 0

    def chat(self, _messages, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return json.dumps({"actions": [{"tool": "inspect", "arguments": {}}]}), {}
        return json.dumps({"actions": [], "reply": "回退完成"}), {}


class AgentModelRunnerTests(unittest.TestCase):
    def test_native_tool_client_receives_unchanged_limits(self):
        client = NativeClient()
        runner = AgentModelRunner(client, Registry, lambda *_: "{}")

        result = runner.invoke([{"role": "user", "content": "test"}], 7)

        self.assertEqual(result, "原生完成")
        self.assertEqual(client.received[3]["max_rounds"], 7)
        self.assertEqual(client.received[3]["max_tokens"], 4096)

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
