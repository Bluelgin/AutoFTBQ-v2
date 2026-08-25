"""Bounded tool-using agent for the editable v2 project."""

from __future__ import annotations

import json
from typing import Callable

from quest_tools import QuestToolbox

from .agent_core.planning import AgentRunPlan, build_run_plan
from .agent_core.transactions import AgentTransactionManager
from .agent_core.tools import AgentToolRegistry
from .agent_core.query_tools import AgentQueryTools
from .agent_core.quest_tools import AgentQuestTools
from .agent_core.ftb_tools import AgentFTBTools
from .agent_core.tool_catalog import build_tool_specs
from .agent_core.model_runner import AgentModelRunner
from .agent_core.messages import AgentMessageBuilder
from .agent_core.scope import AgentScopePolicy
from .project import ProjectStore
from .skill_registry import SkillRegistry


AGENT_SYSTEM_PROMPT = """You are the AutoFTBQ project agent.
You edit the current FTB Quests project only through the provided tools.
Inspect the project before changing it. Search real item IDs instead of guessing.
Read the FTB schema before editing unfamiliar task, reward, quest, chapter, or book fields.
Relevant built-in skills are automatically injected for each request. Follow them directly; only call load_skill when no suitable skill was preloaded.
Make small, reviewable changes and call validate_project after edits.
Use only the provided tools. Never invent filesystem tools such as read_file or write_file.
Call search_items at most 6 times per run; prefer one broad namespace search with limit=100 before targeted searches.
When the user requests 3 or more sequential quests, use add_quest_chain instead of repeated add_quest calls.
When the user requests branches, merges, or prerequisite links, use apply_dependency_plan after reading exact quest IDs.
Use granular object tools instead of replacing complete task/reward lists whenever possible.
Never output a complete quest book JSON. Reply briefly in Chinese and summarize actions taken.
If native tool calls are unavailable, return this exact fallback format:
{"actions":[{"tool":"tool_name","arguments":{}}],"reply":"short status"}
"""


class ProjectAgent:
    MAX_CHECKPOINTS = 16
    READ_ONLY_TOOLS = {
        "get_project_summary", "get_chapter_quests", "get_ftb_schema",
        "list_skills", "load_skill", "get_quest_data", "get_chapter_data",
        "get_quest_sections", "get_book_document", "list_translations",
        "get_document_objects", "search_items", "search_registry", "get_recipe", "validate_project",
    }

    def __init__(
        self,
        store: ProjectStore,
        client,
        toolbox: QuestToolbox | None = None,
        on_action: Callable[[str, dict, object], None] | None = None,
        skills: SkillRegistry | None = None,
        asset_index=None,
    ):
        self.store = store
        self.client = client
        self.toolbox = toolbox or QuestToolbox()
        self.skills = skills or SkillRegistry()
        self.on_action = on_action
        self.asset_index = asset_index
        self.query_tools = AgentQueryTools(store, self.toolbox, self.skills, asset_index)
        self.quest_tools = AgentQuestTools(store)
        self.ftb_tools = AgentFTBTools(store)
        self.history: list[dict] = []
        self.transaction = AgentTransactionManager(
            store, self.MAX_CHECKPOINTS, self._on_checkpoint_created,
        )
        self.run_plan: AgentRunPlan | None = None
        self._tool_registry: AgentToolRegistry | None = None
        self.model_runner = AgentModelRunner(client, lambda: self.tool_registry, self.call_tool)
        self.message_builder = AgentMessageBuilder(AGENT_SYSTEM_PROMPT)
        self.scope_policy = AgentScopePolicy(store, self.READ_ONLY_TOOLS)
        self._run_tool_counts: dict[str, int] = {}
        self.request_context: dict = {}

    # Compatibility aliases keep existing UI/tests stable while transaction
    # ownership moves out of the model orchestration class.
    @property
    def _transaction_snapshot(self):
        return self.transaction.original_snapshot

    @_transaction_snapshot.setter
    def _transaction_snapshot(self, value) -> None:
        self.transaction.original_snapshot = value

    @property
    def _transaction_baseline_errors(self):
        return self.transaction.baseline_errors

    @_transaction_baseline_errors.setter
    def _transaction_baseline_errors(self, value) -> None:
        self.transaction.baseline_errors = set(value)

    @property
    def _transaction_actions(self):
        return self.transaction.actions

    @_transaction_actions.setter
    def _transaction_actions(self, value) -> None:
        self.transaction.actions = list(value)

    @property
    def _transaction_failure(self):
        return self.transaction.failure

    @_transaction_failure.setter
    def _transaction_failure(self, value) -> None:
        self.transaction.failure = str(value or "")

    @property
    def _transaction_checkpoints(self):
        return self.transaction.checkpoints

    @property
    def _tool_rejections(self):
        return self.transaction.rejections

    def set_request_context(self, value: dict | None) -> None:
        self.request_context = dict(value or {})

    @property
    def tool_registry(self) -> AgentToolRegistry:
        if self._tool_registry is None:
            self._tool_registry = AgentToolRegistry(self.tool_specs(), self.READ_ONLY_TOOLS)
        return self._tool_registry

    def _scope_violation(self, name: str, arguments: dict) -> str:
        return self.scope_policy.violation(name, arguments, self.request_context)

    def prepare_run(self, user_message: str) -> AgentRunPlan:
        text = str(user_message or "").strip()
        continuation = text.casefold() in {"继续", "继续执行", "接着做", "continue"}
        if not continuation or self.run_plan is None or self.run_plan.phase == "completed":
            self.run_plan = build_run_plan(text, self.store)
        return self.run_plan

    def export_run_state(self) -> dict:
        return self.run_plan.to_dict() if self.run_plan else {}

    def import_run_state(self, value: dict | None) -> None:
        self.run_plan = AgentRunPlan.from_dict(value)

    @staticmethod
    def _error_keys(issues: list[dict]) -> set[tuple[str, str]]:
        return {
            (str(issue.get("location", "")), str(issue.get("message", "")))
            for issue in issues
            if str(issue.get("severity", "")).casefold() == "error"
        }

    def _begin_transaction(self, resume: bool = False) -> None:
        baseline = self._error_keys(self.store.validate(self.toolbox.all_items))
        self.transaction.begin(baseline, resume=resume)
        self._run_tool_counts = {}

    @property
    def has_pending_changes(self) -> bool:
        return self.transaction.has_pending_changes

    def transaction_summary(self) -> str:
        return self.transaction.summary()

    @property
    def checkpoint_count(self) -> int:
        return self.transaction.checkpoint_count

    def _capture_checkpoint_state(self):
        return self.transaction.capture_step_state()

    def _restore_checkpoint_state(self, snapshot) -> None:
        self.transaction.restore_step_state(snapshot)

    def checkpoint_summary(self) -> list[dict]:
        return self.transaction.checkpoint_summary()

    def _on_checkpoint_created(self, tool_name: str, checkpoint: dict) -> None:
        self._emit("agent_checkpoint", {"tool": tool_name}, {
            "index": checkpoint["index"],
            "label": checkpoint["label"],
            "action_count": checkpoint["action_count"],
        })

    def _create_checkpoint(self, tool_name: str, errors: set[tuple[str, str]]) -> None:
        self.transaction.accept_tool(tool_name, errors)

    def rollback_last_checkpoint(self) -> bool:
        """Undo the latest safe Agent step while preserving earlier work."""
        if not self.transaction.rollback_last():
            return False
        if self.run_plan:
            self.run_plan.phase = "needs_attention"
        return True

    def acceptance_summary(self) -> str:
        if not self.run_plan:
            return "尚无执行计划"
        return "\n".join(
            f"{'通过' if criterion.passed else '未通过'} · {criterion.label}：{criterion.detail}"
            for criterion in self.run_plan.criteria
        )

    def commit_transaction(self) -> bool:
        return self.transaction.commit()

    def rollback_transaction(self) -> bool:
        return self.transaction.rollback_all()

    def _clear_transaction(self) -> None:
        self.transaction.clear()

    def _evaluate_run(self, plan: AgentRunPlan, issues: list[dict]) -> list[str]:
        failures = plan.evaluate(self.store, issues, self._transaction_actions)
        failures.extend(
            f"工具 {name} 的输入仍未修复（{message}）"
            for name, message in self._tool_rejections.items()
        )
        if failures:
            plan.failures = failures
            plan.phase = "needs_attention"
        return failures

    def tool_specs(self) -> list[dict]:
        return build_tool_specs()

    def _emit(self, name: str, arguments: dict, result: object) -> None:
        if self.on_action:
            self.on_action(name, arguments, result)

    def _call_tool_impl(self, name: str, arguments: dict) -> str:
        arguments = arguments if isinstance(arguments, dict) else {}
        query = self.query_tools.execute(name, arguments)
        quest_write = self.quest_tools.execute(name, arguments)
        ftb_write = self.ftb_tools.execute(name, arguments)
        if query.handled:
            result = query.value
        elif quest_write.handled:
            result = quest_write.value
        elif ftb_write.handled:
            result = ftb_write.value
        else:
            result = {
                "error": f"不允许的工具：{name}",
                "recovery": "不要重试或猜测工具名称；请改用当前 tools 列表中的工具继续完成计划。",
            }
        self._emit(name, arguments, result)
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

    def call_tool(self, name: str, arguments: dict) -> str:
        known_tool = self.tool_registry.contains(name)
        self._run_tool_counts[name] = self._run_tool_counts.get(name, 0) + 1
        scope_error = self._scope_violation(name, arguments if isinstance(arguments, dict) else {})
        if scope_error:
            result = {"error": scope_error, "recovery": "请遵守当前作用域，必要时向用户说明需要扩大选择范围。"}
            self._emit(name, arguments, result)
            return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if name == "search_items" and self._run_tool_counts[name] > 6:
            result = {
                "error": "本轮物品搜索已达到 6 次上限",
                "recovery": "请使用已有搜索结果开始创建任务，不要继续搜索。",
            }
            self._emit(name, arguments, result)
            if self.run_plan:
                self.run_plan.record_action(name)
            return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        transactional_write = (
            self.transaction.active and self.tool_registry.is_write(name)
        )
        before_tool = self.transaction.capture_step_state() if transactional_write else None
        try:
            encoded = self._call_tool_impl(name, arguments)
        except Exception as exc:
            if transactional_write and isinstance(exc, (ValueError, TypeError, KeyError)):
                self.transaction.restore_step_state(before_tool)
                result = {
                    "error": str(exc) or type(exc).__name__,
                    "recovery": "本次工具修改已撤销。请根据错误补齐参数或查询 Schema 后重试，不要放弃此前检查点。",
                }
                self.transaction.reject_tool(name, result["error"])
                self._emit("agent_tool_rejected", {"tool": name, **(arguments or {})}, result)
                if self.run_plan:
                    self.run_plan.record_action(f"{name}:rejected")
                return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            if transactional_write:
                self.transaction.restore_step_state(before_tool)
                self._transaction_failure = f"{name}: {exc}"
            raise
        if transactional_write:
            try:
                result = json.loads(encoded)
            except (TypeError, ValueError):
                result = None
            if isinstance(result, dict) and result.get("error"):
                self.transaction.restore_step_state(before_tool)
                self.transaction.reject_tool(name, str(result["error"]))
                self._emit("agent_tool_rejected", {"tool": name, **(arguments or {})}, result)
            else:
                issues = self.store.validate(self.toolbox.all_items)
                current_errors = self._error_keys(issues)
                new_errors = current_errors - self._transaction_baseline_errors
                if new_errors:
                    self.transaction.restore_step_state(before_tool)
                    details = "；".join(message for _location, message in sorted(new_errors)[:3])
                    result = {
                        "error": f"修改未通过本地结构检查：{details}",
                        "recovery": "本次工具修改已撤销。请读取对应 Schema，修正缺失字段后重试；此前检查点已保留。",
                    }
                    self.transaction.reject_tool(name, result["error"])
                    self._emit("agent_tool_rejected", {"tool": name, **(arguments or {})}, result)
                    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                else:
                    self._create_checkpoint(name, current_errors)
        if self.run_plan:
            self.run_plan.record_action(name)
        return encoded

    def _invoke_model(self, messages: list[dict], max_rounds: int) -> str:
        return self.model_runner.invoke(messages, max_rounds)

    def run(self, user_message: str) -> str:
        if self.client is None:
            raise RuntimeError("尚未连接 AI，请先配置 API 或 Ollama")
        request_text = str(user_message or "").strip()
        continuation = request_text.casefold() in {"继续", "继续执行", "接着做", "continue"}
        plan = self.prepare_run(user_message)
        effective_request = plan.request
        plan.phase = "executing"
        plan.attempts += 1
        for step in plan.steps:
            if step.get("id") == "inspect":
                step["status"] = "completed"
            elif step.get("id") == "edit":
                step["status"] = "in_progress"
        self._begin_transaction(resume=continuation)
        self._emit("agent_plan", {"request": effective_request}, plan.to_dict())
        messages = self.message_builder.build(
            history=self.history,
            project_summary=self.store.summary(),
            skill_catalog=self.skills.catalog(),
            matched_skills=self.skills.match(effective_request),
            request_context=self.request_context,
            plan_instructions=plan.instructions(),
            request=effective_request,
        )
        try:
            content = self._invoke_model(messages, 18)
            if self._transaction_failure:
                failure = self._transaction_failure
                plan.phase = "failed"
                plan.failures = [failure]
                self.rollback_transaction()
                return f"本轮修改已自动撤销，因为工具执行失败：{failure}"
            issues = self.store.validate(self.toolbox.all_items)
            new_errors = self._error_keys(issues) - self._transaction_baseline_errors
            if new_errors:
                details = "；".join(message for _location, message in sorted(new_errors)[:3])
                plan.phase = "failed"
                plan.failures = [details]
                self.rollback_transaction()
                return f"本轮修改已自动撤销，因为检查发现新的结构错误：{details}"
            failures = self._evaluate_run(plan, issues)
            self._emit("agent_verify", {"attempt": plan.attempts}, {
                "passed": not failures, "failures": failures,
            })
            if failures:
                plan.phase = "repairing"
                self._emit("agent_repair", {"failures": failures}, {"status": "started"})
                repair_messages = self.message_builder.build_repair(
                    messages, content, failures,
                )
                content = self._invoke_model(repair_messages, 10)
                if self._transaction_failure:
                    failure = self._transaction_failure
                    plan.phase = "failed"
                    plan.failures = [failure]
                    self.rollback_transaction()
                    return f"本轮修改已自动撤销，因为修复阶段工具执行失败：{failure}"
                issues = self.store.validate(self.toolbox.all_items)
                new_errors = self._error_keys(issues) - self._transaction_baseline_errors
                if new_errors:
                    details = "；".join(message for _location, message in sorted(new_errors)[:3])
                    plan.phase = "failed"
                    plan.failures = [details]
                    self.rollback_transaction()
                    return f"本轮修改已自动撤销，因为修复后仍有新的结构错误：{details}"
                failures = self._evaluate_run(plan, issues)
                self._emit("agent_verify", {"attempt": plan.attempts, "repair": True}, {
                    "passed": not failures, "failures": failures,
                })
                if failures:
                    content = (
                        f"{content}\n\n本轮没有冒充完成，仍有 {len(failures)} 项验收条件未满足："
                        + "；".join(failures)
                        + "。可以发送“继续”从当前计划接着处理。"
                    )
            if not self._transaction_actions:
                self._clear_transaction()
            self.history.extend([
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": content},
            ])
            return content
        except Exception:
            # Every accepted write already has a safe checkpoint. Keep it available
            # for continuation instead of discarding the complete run on a network error.
            plan.phase = "interrupted"
            self.transaction.restore_latest()
            raise
