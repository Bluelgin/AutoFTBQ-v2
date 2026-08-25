"""Model transport and JSON action-protocol fallback for the project Agent."""

from __future__ import annotations

import json
import re


class AgentModelRunner:
    def __init__(self, client, registry_provider, tool_handler):
        self.client = client
        self.registry_provider = registry_provider
        self.tool_handler = tool_handler

    def invoke(self, messages: list[dict], max_rounds: int) -> str:
        registry = self.registry_provider()
        if hasattr(self.client, "chat_with_tools"):
            response = self.client.chat_with_tools(
                messages, registry.specs(), self.tool_handler,
                temperature=0.35, max_tokens=4096, max_rounds=max_rounds,
            )
            content = response[0] if isinstance(response, tuple) else response
        else:
            content = self.run_action_protocol(messages)
        envelope = self.action_envelope(content)
        if envelope and envelope.get("actions"):
            content = self.run_action_protocol(messages, content)
        elif envelope:
            content = str(envelope.get("reply", "") or content)
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

    def run_action_protocol(self, messages: list[dict], first_content: str | None = None) -> str:
        specs = self.registry_provider().function_specs()
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
