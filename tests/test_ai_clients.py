import unittest
from unittest.mock import patch

import requests

from ai_clients import (
    DEEPSEEK_MODEL,
    GenericOpenAIClient,
    _response_content,
    create_chat_client,
)


class FakeChatResponse:
    status_code = 200

    def json(self):
        return {
            "choices": [{
                "message": {"content": "{}"},
                "finish_reason": "stop",
            }],
        }


class FakeToolCallResponse:
    status_code = 200

    def json(self):
        return {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "search_items",
                            "arguments": '{"namespace":"create","query":"press"}',
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }


class FakeManyToolCallsResponse:
    status_code = 200

    def json(self):
        return {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": f"call_{index}",
                        "type": "function",
                        "function": {
                            "name": "search_items",
                            "arguments": '{"namespace":"create","query":"gear"}',
                        },
                    } for index in range(8)],
                },
                "finish_reason": "tool_calls",
            }],
        }


class FakeErrorResponse:
    status_code = 400
    text = "tools unsupported"

    def json(self):
        return {"error": self.text}


class FakeMalformedToolResponse:
    status_code = 200

    def json(self):
        return {"result": "provider ignored the OpenAI response schema"}


class FakeReasoningOnlyResponse:
    status_code = 200

    def json(self):
        return {
            "choices": [{
                "message": {
                    "content": None,
                    "reasoning": "hidden reasoning is intentionally not exposed",
                    "reasoning_details": [{"type": "reasoning.text"}],
                },
                "finish_reason": "stop",
            }],
        }


class FakeLegacyFunctionCallResponse:
    status_code = 200

    def json(self):
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "function_call": {
                        "name": "search_items",
                        "arguments": '{"query":"gear"}',
                    },
                },
                "finish_reason": "function_call",
            }],
        }


class AIClientTests(unittest.TestCase):
    def test_custom_provider_uses_supplied_url_and_model(self):
        client = create_chat_client(
            "generic",
            api_key="secret",
            provider="第三方自定义",
            api_url="https://example.test/v1/chat/completions",
            api_model="custom-model",
        )

        self.assertIsInstance(client, GenericOpenAIClient)
        self.assertEqual(client.api_url, "https://example.test/v1/chat/completions")
        self.assertEqual(client.model, "custom-model")

    @patch("ai_clients.time.sleep")
    @patch(
        "ai_clients.requests.post",
        side_effect=[requests.exceptions.ChunkedEncodingError("ended early")] * 5 + [FakeChatResponse()],
    )
    def test_interrupted_response_reconnects_five_times_then_succeeds(self, post, sleep):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")

        self.assertEqual(client.chat([{"role": "user", "content": "test"}]), ("{}", False))
        self.assertEqual(post.call_count, 6)
        self.assertEqual(sleep.call_count, 5)

    @patch("ai_clients.time.sleep")
    @patch(
        "ai_clients.requests.post",
        side_effect=[requests.exceptions.ChunkedEncodingError("ended early")] * 6,
    )
    def test_interrupted_response_reports_after_five_failed_reconnects(self, post, sleep):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")

        with self.assertRaisesRegex(RuntimeError, "自动重连 5 次"):
            client.chat([{"role": "user", "content": "test"}])
        self.assertEqual(post.call_count, 6)
        self.assertEqual(sleep.call_count, 5)

    def test_legacy_custom_url_does_not_inherit_deepseek_options(self):
        client = create_chat_client(
            "generic",
            api_key="secret",
            api_url="https://example.test/v1/chat/completions",
            api_model="custom-model",
        )

        self.assertFalse(client.omit_temperature)
        self.assertEqual(client.request_overrides, {})

    def test_legacy_deepseek_client_uses_current_flash_model(self):
        client = create_chat_client("deepseek", api_key="secret")

        self.assertEqual(DEEPSEEK_MODEL, "deepseek-v4-flash")
        self.assertEqual(client.model, "deepseek-v4-flash")
        self.assertEqual(client.request_overrides, {"thinking": {"type": "disabled"}})

    @patch("ai_clients.requests.post", return_value=FakeChatResponse())
    def test_moonshot_migrates_old_default_and_omits_fixed_temperature(self, post):
        client = create_chat_client(
            "generic",
            api_key="secret",
            provider="Moonshot",
            api_model="moonshot-v1-8k",
        )

        client.chat([{"role": "user", "content": "test"}], temperature=0.45)

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "kimi-k2.6")
        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["thinking"], {"type": "disabled"})

    def test_response_content_supports_text_parts(self):
        payload = {
            "choices": [{
                "message": {"content": [{"type": "text", "text": "hello"}, {"text": " world"}]},
                "finish_reason": "length",
            }],
        }

        self.assertEqual(_response_content(payload), ("hello world", True))

    def test_response_content_supports_nested_text_objects(self):
        payload = {
            "choices": [{
                "message": {"content": {"type": "text", "text": {"value": "hello"}}},
                "finish_reason": "stop",
            }],
        }

        self.assertEqual(_response_content(payload), ("hello", False))

    def test_response_content_explains_reasoning_token_exhaustion(self):
        payload = {
            "choices": [{
                "message": {"content": None, "reasoning_content": "internal reasoning"},
                "finish_reason": "length",
            }],
        }

        with self.assertRaisesRegex(ValueError, "推理内容耗尽"):
            _response_content(payload)

    def test_response_content_rejects_wrong_shape(self):
        with self.assertRaisesRegex(ValueError, "choices"):
            _response_content({"message": "not-openai-compatible"})

    @patch("ai_clients.requests.post", side_effect=[FakeReasoningOnlyResponse(), FakeChatResponse()])
    def test_plain_chat_recovers_when_model_returns_reasoning_without_visible_text(self, post):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")

        with self.assertLogs("autoftbq.v2", level="WARNING") as captured:
            content, truncated = client.chat([{"role": "user", "content": "test"}], max_tokens=512)

        self.assertEqual((content, truncated), ("{}", False))
        self.assertEqual(post.call_count, 2)
        self.assertNotIn("hidden reasoning", "\n".join(captured.output))
        recovery = post.call_args_list[1].kwargs["json"]
        self.assertNotIn("tools", recovery)
        self.assertIn("visible final answer", recovery["messages"][-1]["content"])

    @patch("ai_clients.requests.post", side_effect=[FakeToolCallResponse(), FakeChatResponse()])
    def test_tool_loop_executes_handler_and_returns_final_content(self, post):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")
        calls = []

        content, truncated = client.chat_with_tools(
            [{"role": "user", "content": "generate"}],
            [{"type": "function", "function": {"name": "search_items", "parameters": {}}}],
            lambda name, arguments: calls.append((name, arguments)) or "[]",
        )

        self.assertEqual(content, "{}")
        self.assertFalse(truncated)
        self.assertEqual(calls[0][0], "search_items")
        second_messages = post.call_args_list[1].kwargs["json"]["messages"]
        self.assertEqual(second_messages[-1]["role"], "tool")

    @patch(
        "ai_clients.requests.post",
        side_effect=[FakeToolCallResponse(), FakeReasoningOnlyResponse(), FakeChatResponse()],
    )
    def test_tool_loop_recovers_visible_answer_without_losing_tool_results(self, post):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")

        content, truncated = client.chat_with_tools(
            [{"role": "user", "content": "generate"}],
            [{"type": "function", "function": {"name": "search_items", "parameters": {}}}],
            lambda *_: "[]",
        )

        self.assertEqual((content, truncated), ("{}", False))
        recovery_messages = post.call_args_list[2].kwargs["json"]["messages"]
        self.assertTrue(any(message.get("role") == "tool" for message in recovery_messages))
        self.assertIn("visible final answer", recovery_messages[-1]["content"])
        self.assertTrue(client._tool_support)

    @patch("ai_clients.requests.post", side_effect=[FakeLegacyFunctionCallResponse(), FakeChatResponse()])
    def test_tool_loop_supports_legacy_function_call_shape(self, post):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")
        calls = []

        content, _ = client.chat_with_tools(
            [{"role": "user", "content": "generate"}],
            [{"type": "function", "function": {"name": "search_items", "parameters": {}}}],
            lambda name, arguments: calls.append((name, arguments)) or "[]",
        )

        self.assertEqual(content, "{}")
        self.assertEqual(calls, [("search_items", {"query": "gear"})])
        assistant = post.call_args_list[1].kwargs["json"]["messages"][1]
        self.assertIn("tool_calls", assistant)
        self.assertNotIn("function_call", assistant)

    @patch("ai_clients.requests.post", side_effect=[FakeManyToolCallsResponse(), FakeChatResponse()])
    def test_tool_loop_keeps_bounded_calls_and_results_in_sync(self, post):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")
        calls = []

        client.chat_with_tools(
            [{"role": "user", "content": "generate"}],
            [{"type": "function", "function": {"name": "search_items", "parameters": {}}}],
            lambda name, arguments: calls.append((name, arguments)) or "[]",
        )

        second_messages = post.call_args_list[1].kwargs["json"]["messages"]
        assistant = next(message for message in second_messages if message.get("role") == "assistant")
        tool_results = [message for message in second_messages if message.get("role") == "tool"]
        self.assertEqual(len(assistant["tool_calls"]), 6)
        self.assertEqual(len(tool_results), 6)
        self.assertEqual(len(calls), 6)

    @patch("ai_clients.requests.post", side_effect=[FakeToolCallResponse(), FakeChatResponse()])
    def test_tool_loop_final_synthesis_removes_tools(self, post):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")

        client.chat_with_tools(
            [{"role": "user", "content": "generate"}],
            [{"type": "function", "function": {"name": "search_items", "parameters": {}}}],
            lambda *_: "[]",
            max_rounds=1,
        )

        final_payload = post.call_args_list[1].kwargs["json"]
        self.assertNotIn("tools", final_payload)
        self.assertNotIn("tool_choice", final_payload)
        self.assertIn("Stop calling tools", final_payload["messages"][-1]["content"])

    @patch("ai_clients.requests.post", side_effect=[FakeToolCallResponse()] * 8 + [FakeChatResponse()])
    def test_tool_loop_can_complete_workflows_longer_than_six_rounds(self, post):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")
        calls = []

        content, _truncated = client.chat_with_tools(
            [{"role": "user", "content": "generate a complete workflow"}],
            [{"type": "function", "function": {"name": "search_items", "parameters": {}}}],
            lambda name, _arguments: calls.append(name) or "[]",
            max_rounds=12,
        )

        self.assertEqual(content, "{}")
        self.assertEqual(len(calls), 8)
        self.assertEqual(post.call_count, 9)

    @patch("ai_clients.requests.post", side_effect=[FakeErrorResponse(), FakeChatResponse()])
    def test_tool_rejection_falls_back_and_is_cached(self, post):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")

        self.assertEqual(
            client.chat_with_tools(
                [{"role": "user", "content": "generate"}],
                [{"type": "function", "function": {"name": "search_items", "parameters": {}}}],
                lambda *_: "[]",
            )[0],
            "{}",
        )

        self.assertFalse(client._tool_support)
        self.assertEqual(post.call_count, 2)

    @patch("ai_clients.requests.post", side_effect=[FakeMalformedToolResponse(), FakeChatResponse()])
    def test_malformed_tool_response_falls_back_to_plain_chat(self, post):
        client = GenericOpenAIClient("secret", "https://example.test/chat", "model")

        content, truncated = client.chat_with_tools(
            [{"role": "user", "content": "generate"}],
            [{"type": "function", "function": {"name": "search_items", "parameters": {}}}],
            lambda *_: "[]",
        )

        self.assertEqual((content, truncated), ("{}", False))
        self.assertFalse(client._tool_support)
        self.assertEqual(post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
