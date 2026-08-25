"""AI client adapters with one shared chat contract."""

from __future__ import annotations

import json
import logging
import time
from typing import Protocol

import requests

try:
    from . import ollama_adapter
    from .ai_providers import PROVIDER_PRESETS, normalize_provider, resolve_provider_model
except ImportError:
    import ollama_adapter
    from ai_providers import PROVIDER_PRESETS, normalize_provider, resolve_provider_model


DEEPSEEK_API_URL = PROVIDER_PRESETS["DeepSeek"]["chat_url"]
DEEPSEEK_MODEL = PROVIDER_PRESETS["DeepSeek"]["model"]
API_TIMEOUT = 300
MAX_RECONNECTS = 5
RETRY_DELAY = 3
MAX_TOOL_ROUNDS = 24
MAX_TOOL_CALLS = 48
LOGGER = logging.getLogger("autoftbq.v2")


class ChatClient(Protocol):
    def chat(self, messages, temperature=0.7, max_tokens=8192):
        """Return ``(content, was_truncated)``."""


def _content_text(value) -> str | None:
    """Normalize common OpenAI-compatible content variants without exposing reasoning."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_content_text(part) for part in value]
        return "".join(part for part in parts if part is not None)
    if isinstance(value, dict):
        for key in ("text", "content", "value", "output_text"):
            if key in value:
                text = _content_text(value[key])
                if text is not None:
                    return text
    return None


def _response_content(payload):
    """Read an OpenAI-compatible text response with useful shape errors."""
    if not isinstance(payload, dict):
        raise ValueError("API 返回值不是 JSON 对象")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("API 返回值缺少 choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("API 返回值缺少 choices[0].message")
    content = _content_text(message.get("content"))
    if content is None:
        content = _content_text(message.get("text"))
    if content is None:
        content = _content_text(choices[0].get("text"))
    truncated = choices[0].get("finish_reason", "stop") == "length"
    reasoning = (
        message.get("reasoning_content")
        or message.get("reasoning")
        or message.get("reasoning_details")
    )
    if (content is None or not content.strip()) and truncated and reasoning:
        raise ValueError("模型的推理内容耗尽了输出上限，尚未返回最终答案；请提高 max_tokens")
    refusal = _content_text(message.get("refusal"))
    if (content is None or not content.strip()) and refusal:
        raise ValueError(f"模型拒绝了本次请求：{refusal[:160]}")
    if content is None or not content.strip():
        if reasoning:
            raise ValueError("模型只返回了推理过程，没有返回可见的最终答案")
        raise ValueError("API 返回的 message.content 不是文本")
    return content, truncated


def _safe_response_shape(payload) -> dict:
    """Describe a response for logs without recording content or hidden reasoning."""
    choice = payload.get("choices", [{}])[0] if isinstance(payload, dict) else {}
    choice = choice if isinstance(choice, dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = message.get("content")
    reasoning = message.get("reasoning_content", message.get("reasoning"))
    return {
        "finish_reason": choice.get("finish_reason"),
        "content_type": type(content).__name__,
        "content_chars": len(content) if isinstance(content, str) else None,
        "reasoning_type": type(reasoning).__name__,
        "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else None,
        "reasoning_details": len(message.get("reasoning_details") or []),
        "tool_calls": len(message.get("tool_calls") or []),
        "message_keys": sorted(message.keys()),
    }


class GenericOpenAIClient:
    """Minimal OpenAI Chat Completions compatible client."""

    def __init__(
        self,
        api_key,
        api_url,
        model,
        timeout=API_TIMEOUT,
        omit_temperature=False,
        request_overrides=None,
    ):
        if not api_url:
            raise ValueError("未配置 API URL")
        if not model:
            raise ValueError("未配置模型 ID")
        self.api_url = api_url
        self.model = model
        self.timeout = timeout
        self.omit_temperature = omit_temperature
        self.request_overrides = dict(request_overrides or {})
        self._tool_support = None
        self.headers = {
            "Authorization": f"Bearer {str(api_key).strip()}",
            "Content-Type": "application/json",
            "User-Agent": "AutoFTBQ",
        }

    def _payload(self, messages, temperature, max_tokens):
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if not self.omit_temperature:
            payload["temperature"] = temperature
        payload.update(self.request_overrides)
        return payload

    def _post(self, payload):
        for attempt in range(MAX_RECONNECTS + 1):
            try:
                response = requests.post(
                    self.api_url,
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout,
                )
                if response.status_code == 200:
                    body = response.json()
                    if not isinstance(body, dict):
                        raise RuntimeError("API 返回值不是 JSON 对象")
                    return body
                if response.status_code == 401:
                    raise RuntimeError("API Key 无效，请检查后重试")
                if response.status_code == 402:
                    raise RuntimeError("账户额度不足，请检查 API 余额")
                if response.status_code in (400, 403, 404, 422):
                    raise RuntimeError(f"API 请求无效（HTTP {response.status_code}）：{response.text[:200]}")
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"API 请求失败（HTTP {response.status_code}）：{response.text[:200]}")
                if attempt < MAX_RECONNECTS:
                    retry_after = response.headers.get("Retry-After", "")
                    delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else RETRY_DELAY * (attempt + 1)
                    LOGGER.warning(
                        "AI service temporarily unavailable (HTTP %s); reconnecting %s/%s in %.1fs",
                        response.status_code, attempt + 1, MAX_RECONNECTS, min(delay, 30),
                    )
                    time.sleep(min(delay, 30))
                    continue
                raise RuntimeError(f"API 服务暂时不可用（HTTP {response.status_code}）")
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ContentDecodingError,
                requests.exceptions.JSONDecodeError,
                json.JSONDecodeError,
            ) as exc:
                if attempt < MAX_RECONNECTS:
                    delay = min(RETRY_DELAY * (attempt + 1), 30)
                    LOGGER.warning(
                        "AI request connection interrupted (%s); reconnecting %s/%s in %.1fs",
                        type(exc).__name__, attempt + 1, MAX_RECONNECTS, delay,
                    )
                    time.sleep(delay)
                    continue
                if isinstance(exc, requests.exceptions.Timeout):
                    raise RuntimeError("API 请求超时，自动重连 5 次后仍未恢复") from exc
                raise RuntimeError(f"API 连接中断，自动重连 5 次后仍未恢复：{exc}") from exc
            except requests.RequestException as exc:
                raise RuntimeError(f"API 网络请求失败：{exc}") from exc
        raise RuntimeError("API 请求失败（自动重连次数耗尽）")

    def chat(self, messages, temperature=0.7, max_tokens=8192):
        body = self._post(self._payload(messages, temperature, max_tokens))
        try:
            return _response_content(body)
        except (TypeError, ValueError):
            choices = body.get("choices") if isinstance(body, dict) else None
            message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
            if not isinstance(message, dict):
                raise
            LOGGER.warning("AI chat returned no visible text: shape=%s", _safe_response_shape(body))
            return self._recover_visible_content(messages, temperature, max_tokens, body)

    def _recover_visible_content(self, conversation, temperature, max_tokens, response_body):
        LOGGER.warning(
            "AI response had no visible final text; requesting synthesis: shape=%s",
            _safe_response_shape(response_body),
        )
        recovery_messages = [dict(message) for message in conversation]
        recovery_messages.append({
            "role": "user",
            "content": (
                "Return the concise visible final answer now. Do not call more tools and do not "
                "return hidden reasoning only. Summarize the work completed from the tool results."
            ),
        })
        payload = self._payload(recovery_messages, temperature, max(2048, int(max_tokens)))
        body = self._post(payload)
        try:
            return _response_content(body)
        except (TypeError, ValueError) as exc:
            LOGGER.warning("AI synthesis still had no visible text: shape=%s", _safe_response_shape(body))
            raise ValueError(f"模型连续两次没有返回可见答案：{exc}") from exc

    def chat_with_tools(
        self,
        messages,
        tools,
        tool_handler,
        temperature=0.7,
        max_tokens=8192,
        max_rounds=3,
    ):
        """Run a bounded tool loop, falling back once when a provider rejects tools."""
        if self._tool_support is False or not tools:
            return self.chat(messages, temperature, max_tokens)
        conversation = [dict(message) for message in messages]
        tool_call_count = 0
        for round_index in range(max(1, min(int(max_rounds), MAX_TOOL_ROUNDS))):
            payload = self._payload(conversation, temperature, max_tokens)
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            try:
                body = self._post(payload)
            except RuntimeError as exc:
                unsupported = any(
                    marker in str(exc)
                    for marker in ("HTTP 400", "HTTP 403", "HTTP 404", "HTTP 422")
                )
                if unsupported:
                    self._tool_support = False
                    return self.chat(messages, temperature, max_tokens)
                raise
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                self._tool_support = False
                return self.chat(messages, temperature, max_tokens)
            message = choices[0].get("message")
            if not isinstance(message, dict):
                self._tool_support = False
                return self.chat(messages, temperature, max_tokens)
            tool_calls = message.get("tool_calls")
            legacy_call = message.get("function_call")
            if (not isinstance(tool_calls, list) or not tool_calls) and isinstance(legacy_call, dict):
                tool_calls = [{
                    "id": f"legacy_call_{round_index}",
                    "type": "function",
                    "function": legacy_call,
                }]
            if not isinstance(tool_calls, list) or not tool_calls:
                try:
                    result = _response_content(body)
                except (TypeError, ValueError) as exc:
                    LOGGER.warning("AI tool loop returned no visible text: shape=%s", _safe_response_shape(body))
                    result = self._recover_visible_content(conversation, temperature, max_tokens, body)
                self._tool_support = True
                return result
            self._tool_support = True
            remaining_calls = MAX_TOOL_CALLS - tool_call_count
            bounded_calls = [call for call in tool_calls if isinstance(call, dict)][:min(6, remaining_calls)]
            if not bounded_calls:
                self._tool_support = False
                return self.chat(messages, temperature, max_tokens)
            tool_call_count += len(bounded_calls)
            bounded_message = dict(message)
            bounded_message.setdefault("role", "assistant")
            bounded_message.pop("function_call", None)
            bounded_message["tool_calls"] = bounded_calls
            conversation.append(bounded_message)
            for call in bounded_calls:
                function = call.get("function", {}) if isinstance(call, dict) else {}
                name = str(function.get("name", ""))
                try:
                    arguments = json.loads(function.get("arguments", "{}") or "{}")
                except (TypeError, ValueError):
                    arguments = {}
                try:
                    result = tool_handler(name, arguments)
                except Exception as exc:
                    result = json.dumps({"error": str(exc)}, ensure_ascii=False)
                conversation.append({
                    "role": "tool",
                    "tool_call_id": str(call.get("id", f"tool_{round_index}")),
                    "name": name,
                    "content": str(result),
                })
            if tool_call_count >= MAX_TOOL_CALLS:
                break
        conversation.append({
            "role": "user",
            "content": (
                "Stop calling tools. Using the tool results already provided, "
                "return the final answer in the exact format requested by the original prompt."
            ),
        })
        payload = self._payload(conversation, temperature, max_tokens)
        body = self._post(payload)
        try:
            return _response_content(body)
        except (TypeError, ValueError):
            LOGGER.warning("AI final synthesis returned no visible text: shape=%s", _safe_response_shape(body))
            return self._recover_visible_content(conversation, temperature, max_tokens, body)


class DeepSeekClient(GenericOpenAIClient):
    def __init__(self, api_key):
        preset = PROVIDER_PRESETS["DeepSeek"]
        super().__init__(
            api_key,
            DEEPSEEK_API_URL,
            DEEPSEEK_MODEL,
            omit_temperature=preset.get("omit_temperature", False),
            request_overrides=preset.get("request_overrides"),
        )


def create_chat_client(engine, api_key=None, ollama_model=None, provider=None, api_url=None, api_model=None):
    """Create a client while keeping legacy engine names compatible."""
    if engine == "ollama":
        return ollama_adapter.OllamaClient(model=ollama_model or "qwen2.5-coder:7b")
    if engine == "dummy":
        return None
    if engine == "deepseek" and not provider and not api_url and not api_model:
        return DeepSeekClient(api_key or "")

    normalized = normalize_provider(provider)
    preset = PROVIDER_PRESETS.get(normalized, {})
    final_url = api_url or preset.get("chat_url") or DEEPSEEK_API_URL
    uses_preset = bool(provider) or not api_url or api_url == preset.get("chat_url")
    final_model = (
        resolve_provider_model(normalized, api_model)
        if uses_preset
        else (api_model or preset.get("model"))
    )
    return GenericOpenAIClient(
        api_key or "",
        final_url,
        final_model,
        omit_temperature=preset.get("omit_temperature", False) if uses_preset else False,
        request_overrides=preset.get("request_overrides") if uses_preset else None,
    )
