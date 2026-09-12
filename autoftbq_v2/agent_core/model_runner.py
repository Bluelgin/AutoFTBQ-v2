"""Model transport and JSON action-protocol fallback for the project Agent."""

from __future__ import annotations

import json
import re


class AgentModelRunner:
    def __init__(self, client, registry_provider, tool_handler):
        self.client = client
        self.registry_provider = registry_provider
        self.tool_handler = tool_handler
        self.last_truncated = False

    def invoke_with_specs(self, messages, specs, *, temperature=0.35,
                          max_tokens=4096, max_rounds=10, **options):
        """Shared transport entry for desktop and live-game tool adapters."""
        if hasattr(self.client, "chat_with_tools"):
            response = self.client.chat_with_tools(
                messages, specs, self.tool_handler, temperature=temperature,
                max_tokens=max_tokens, max_rounds=max_rounds, **options,
            )
            content = response[0] if isinstance(response, tuple) else response
            truncated = bool(isinstance(response, tuple) and len(response) > 1 and response[1] is True)
            envelope = self.action_envelope(content)
            if not envelope or not envelope.get("actions"):
                return str(content), truncated
        else:
            content = None
        names = {spec["function"]["name"] for spec in specs}
        conversation = [*messages, {"role": "system", "content":
            "Return JSON {\"actions\":[{\"tool\":name,\"arguments\":{}}],\"reply\":text}. "
            "Use only these tools: " + json.dumps(specs, ensure_ascii=False)}]
        for _ in range(max_rounds):
            if content is None:
                response = self.client.chat(conversation, temperature=temperature, max_tokens=max_tokens)
                content = response[0] if isinstance(response, tuple) else response
            envelope = self.action_envelope(content)
            if not envelope or not envelope.get("actions"):
                return str(envelope.get("reply", "") if envelope else content), False
            results = []
            for action in envelope["actions"][:8]:
                if not isinstance(action, dict):
                    continue
                name = str(action.get("tool", ""))
                args = action.get("arguments", {})
                try:
                    if name not in names or not isinstance(args, dict):
                        raise ValueError("Unknown tool or invalid arguments")
                    result = self.tool_handler(name, args)
                except Exception as exc:
                    result = json.dumps({"error": str(exc)})
                from ai_clients import _append_tool_trace
                _append_tool_trace(options.get("trace_sink"), name, args if isinstance(args, dict) else {}, result)
                results.append({"tool": name, "result": result})
            conversation.extend([
                {"role": "assistant", "content": str(content)},
                {"role": "user", "content": json.dumps(results, ensure_ascii=False)},
            ])
            content = None
        return "本批执行预算已用完，目标尚未确认完成。", True

    def invoke(
        self, messages: list[dict], max_rounds: int, tool_names=None,
        minimum_reasoning_effort: str | None = None,
    ) -> str:
        registry = self.registry_provider()
        specs = registry.specs(tool_names)
        original_effort = getattr(self.client, "reasoning_effort", None)
        if minimum_reasoning_effort and original_effort is not None:
            levels = {"low": 1, "medium": 2, "high": 3}
            if levels.get(str(original_effort), 0) < levels.get(minimum_reasoning_effort, 0):
                self.client.reasoning_effort = minimum_reasoning_effort
        try:
            content, self.last_truncated = self.invoke_with_specs(
                messages, specs, max_rounds=max_rounds,
            )
            envelope = self.action_envelope(content)
            if envelope and envelope.get("actions"):
                content = self.run_action_protocol(messages, content, tool_names)
            elif envelope:
                content = str(envelope.get("reply", "") or content)
        finally:
            if original_effort is not None:
                self.client.reasoning_effort = original_effort
        return str(content).strip() or "操作已完成，请在左侧检查任务书。"

    @staticmethod
    def action_envelope(content: str) -> dict | None:
        text = str(content or "").strip()
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        candidates = [fenced.group(1)] if fenced else []
        candidates.append(text)
        for candidate in candidates:
            try:
                value = json.loads(candidate)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict) and isinstance(value.get("actions", []), list):
                return value
        return None

    def run_action_protocol(self, messages: list[dict], first_content: str | None = None, tool_names=None) -> str:
        specs = self.registry_provider().function_specs(tool_names)
        conversation = [
            *messages,
            {
                "role": "system",
                "content": (
                    "Native tools are unavailable. Use only this JSON Action protocol. "
                    f"Available tools: {json.dumps(specs, ensure_ascii=False)}"
                ),
            },
        ]
        content = first_content
        last_reply = ""
        for _round in range(5):
            if content is None:
                content, _ = self.client.chat(conversation, temperature=0.35, max_tokens=4096)
            envelope = self.action_envelope(content)
            if envelope is None:
                return str(content)
            last_reply = str(envelope.get("reply", "") or last_reply)
            actions = envelope.get("actions", [])[:8]
            if not actions:
                return last_reply or "操作已完成，请在左侧检查任务书。"
            results = []
            for action in actions:
                if not isinstance(action, dict):
                    continue
                name = str(action.get("tool", ""))
                arguments = action.get("arguments", {})
                try:
                    result = json.loads(self.tool_handler(name, arguments))
                except Exception as exc:
                    result = {"error": str(exc)}
                results.append({"tool": name, "result": result})
            conversation.extend([
                {"role": "assistant", "content": str(content)},
                {
                    "role": "user",
                    "content": (
                        f"工具结果：{json.dumps(results, ensure_ascii=False)}\n"
                        "继续完成用户目标。需要操作就返回下一批 actions；完成后返回 actions 为空的 JSON。"
                    ),
                },
            ])
            content = None
        return last_reply or "已达到本轮工具调用上限，请检查当前项目后继续。"
