"""Structured request intents shared by the Agent composer and scope guard."""

from __future__ import annotations

from dataclasses import dataclass


COMMANDS = (
    ("/生成", "generate", "创建章节、主线或支线"),
    ("/改进", "improve", "优化选中的任务或章节"),
    ("/检查", "inspect", "只分析问题，不主动修改"),
    ("/补全", "complete", "补齐玩法、阶段或任务断层"),
    ("/重排", "layout", "只调整节点布局"),
    ("/连线", "connect", "规划或修复前置关系"),
    ("/润色", "polish", "只修改标题与描述"),
    ("/解释", "explain", "解释选中内容或属性"),
)

INTENT_LABELS = {
    "generate": "生成",
    "improve": "改进",
    "inspect": "检查",
    "complete": "补全",
    "layout": "重排",
    "connect": "连线",
    "polish": "润色",
    "explain": "解释",
    "auto": "自动识别",
}

COMMAND_INTENTS = {command: intent for command, intent, _description in COMMANDS}
SCOPE_REQUIRED = {"improve", "complete", "layout", "connect", "polish"}
WHOLE_SCOPE_WORDS = ("整个任务书", "全部任务书", "全任务书", "所有章节", "全局")
CURRENT_CHAPTER_WORDS = ("当前章节", "这个章节", "本章节", "这一章")


@dataclass(frozen=True)
class ParsedRequest:
    raw: str
    intent: str
    command: str = ""
    instruction: str = ""

    @property
    def explicit(self) -> bool:
        return bool(self.command)


def parse_request(text: str) -> ParsedRequest:
    raw = str(text or "").strip()
    command = ""
    instruction = raw
    if raw.startswith("/"):
        first, _, remainder = raw.partition(" ")
        command = first.strip()
        instruction = remainder.strip()
        if command in COMMAND_INTENTS:
            return ParsedRequest(raw, COMMAND_INTENTS[command], command, instruction)
        return ParsedRequest(raw, "unknown", command, instruction)

    lowered = raw.casefold()
    rules = (
        ("layout", ("重排", "重新排列", "布局", "排版", "整理位置")),
        ("connect", ("连线", "前置关系", "依赖关系", "连接任务")),
        ("polish", ("润色", "优化文案", "改写描述", "改写标题")),
        ("inspect", ("检查", "审计", "分析问题", "找出问题")),
        ("complete", ("补全", "补齐", "缺失玩法", "内容断层")),
        ("improve", ("改进", "优化", "完善", "修复现有")),
        ("generate", ("生成", "创建", "新建", "制作", "设计章节")),
        ("explain", ("解释", "说明", "怎么用")),
    )
    for intent, words in rules:
        if any(word in lowered for word in words):
            return ParsedRequest(raw, intent, "", raw)
    return ParsedRequest(raw, "auto", "", raw)


def wants_whole_book(text: str) -> bool:
    value = str(text or "")
    return any(word in value for word in WHOLE_SCOPE_WORDS)


def wants_current_chapter(text: str) -> bool:
    value = str(text or "")
    return any(word in value for word in CURRENT_CHAPTER_WORDS)


def structured_prompt(parsed: ParsedRequest, scope: dict) -> str:
    chapter_labels = [str(value) for value in scope.get("chapter_labels", [])]
    quest_labels = [str(value) for value in scope.get("quest_labels", [])]
    scope_lines = []
    if chapter_labels:
        scope_lines.append("章节：" + "、".join(chapter_labels))
    if quest_labels:
        scope_lines.append("任务：" + "、".join(quest_labels))
    if not scope_lines:
        scope_lines.append("整个任务书" if scope.get("whole_book") else "由 Agent 根据要求判断")
    instruction = parsed.instruction or {
        "improve": "改进选中的内容",
        "inspect": "检查当前范围并报告问题",
        "complete": "补全选中范围内缺失的内容",
        "layout": "整理选中范围的节点布局",
        "connect": "为选中范围规划合理的前置关系",
        "polish": "润色选中内容的标题与描述",
        "explain": "解释选中的内容",
    }.get(parsed.intent, parsed.raw)
    permissions = (
        "只能修改上述明确作用域；不得修改、删除或移动作用域外的现有对象。"
        if scope.get("strict") else
        "作用域未锁定，可根据用户明确要求操作任务书。"
    )
    return (
        "[AutoFTBQ 结构化请求]\n"
        f"执行模式：{INTENT_LABELS.get(parsed.intent, '自动识别')}\n"
        f"用户要求：{instruction}\n"
        "目标范围：" + "；".join(scope_lines) + "\n"
        f"权限边界：{permissions}\n"
        "优先读取目标对象的现有数据，保留未要求修改的 ID、字段、奖励和布局。"
    )


def prepare_request(
    text: str,
    store,
    *,
    current_chapter_id: str = "",
    selected_chapter_ids=(),
    selected_quest_ids=(),
    previous_scope: dict | None = None,
) -> tuple[str | None, dict | None, str]:
    """Resolve user text and editor selection into one bounded Agent request."""
    raw = str(text or "").strip()
    if raw.casefold() in {"继续", "继续执行", "接着做", "continue"}:
        return raw, dict(previous_scope or {}), ""
    parsed = parse_request(raw)
    if parsed.intent == "unknown":
        return None, None, f"不认识指令“{parsed.command}”。输入 / 可以查看可用指令。"

    selected_chapters = {str(value) for value in selected_chapter_ids}
    selected_quests = {str(value) for value in selected_quest_ids}
    whole_book = wants_whole_book(parsed.raw)
    if whole_book:
        selected_chapters.clear()
        selected_quests.clear()
    elif not selected_chapters and not selected_quests and wants_current_chapter(parsed.raw):
        if current_chapter_id:
            selected_chapters.add(current_chapter_id)

    if parsed.intent == "generate" and parsed.explicit and not parsed.instruction:
        return None, None, "请在 /生成 后描述要创建的章节、任务或支线。"
    if parsed.explicit and parsed.intent in SCOPE_REQUIRED and not whole_book:
        if not selected_chapters and not selected_quests:
            return None, None, (
                f"“{INTENT_LABELS[parsed.intent]}”需要明确范围。请 Alt + 点击任务或章节，"
                "或在要求中写明“当前章节”或“整个任务书”。"
            )
        if parsed.intent == "connect" and not selected_chapters and len(selected_quests) < 2:
            return None, None, "连线至少需要选择两个任务，或选择一个完整章节。"

    quest_chapters = {
        found[0].id
        for quest_id in selected_quests
        for found in [store.quest(quest_id)]
        if found is not None
    }
    chapter_labels = [
        chapter.title for chapter in store.project.chapters if chapter.id in selected_chapters
    ]
    quest_labels = [
        quest.title
        for chapter in store.project.chapters
        for quest in chapter.quests
        if quest.id in selected_quests
    ]
    scope = {
        "intent": parsed.intent,
        "strict": bool(selected_chapters or selected_quests) and not whole_book,
        "whole_book": whole_book,
        "chapter_ids": sorted(selected_chapters),
        "quest_ids": sorted(selected_quests),
        "creation_chapter_ids": sorted(selected_chapters | quest_chapters),
        "chapter_labels": chapter_labels,
        "quest_labels": quest_labels,
    }
    return structured_prompt(parsed, scope), scope, ""
