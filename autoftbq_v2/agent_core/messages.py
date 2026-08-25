"""Prompt message construction for the project Agent."""

from __future__ import annotations

import json


class AgentMessageBuilder:
    """Build model messages without owning execution or transaction state."""

    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def build(
        self,
        *,
        history: list[dict],
        project_summary: dict,
        skill_catalog: list[dict],
        matched_skills: list[dict],
        request_context: dict,
        plan_instructions: str,
        request: str,
    ) -> list[dict]:
        context = json.dumps(project_summary, ensure_ascii=False)
        scope = json.dumps(request_context, ensure_ascii=False)
        catalog = json.dumps(skill_catalog, ensure_ascii=False)
        skills = json.dumps(matched_skills, ensure_ascii=False)
        return [
            {"role": "system", "content": self.system_prompt},
            *history[-10:],
            {
                "role": "user",
                "content": (
                    f"当前项目摘要：{context}\n"
                    f"可按需加载的 Skills：{catalog}\n\n"
                    f"已自动启用的 Skills（直接遵循，不要再次加载）：{skills}\n\n"
                    f"本轮结构化模式与写入作用域：{scope}\n"
                    "软件会拒绝越过作用域的修改；遇到拒绝时不要反复调用。\n\n"
                    f"{plan_instructions}\n\n"
                    f"用户要求：{request}"
                ),
            },
        ]

    @staticmethod
    def build_repair(messages: list[dict], content: str, failures: list[str]) -> list[dict]:
        return [
            *messages,
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": (
                    "自动验收未通过，请不要重复已经完成的工作。读取当前项目后，只修复以下缺口：\n"
                    + "\n".join(f"- {failure}" for failure in failures)
                    + "\n必须再次调用必要工具并完成这些条件，然后检查项目。"
                ),
            },
        ]
