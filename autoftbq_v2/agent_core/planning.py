"""Deterministic planning and acceptance checks for Agent editing runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re


_CHINESE_NUMBERS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}


def _metrics(store) -> dict:
    quests = [quest for chapter in store.project.chapters for quest in chapter.quests]
    return {
        "chapter_count": len(store.project.chapters),
        "quest_count": len(quests),
        "quest_ids": [quest.id for quest in quests],
        "dependency_count": sum(len(quest.dependencies) for quest in quests),
    }


def _requested_quest_count(text: str) -> int:
    matches = re.findall(
        r"(?:共|至少|创建|添加|生成|制作|安排)?\s*(\d{1,3})\s*(?:个|项|条|道)?"
        r"\s*[^，。；,\n]{0,10}?(?:任务|节点)",
        text,
    )
    if matches:
        return max(1, min(int(matches[-1]), 100))
    for word, value in sorted(_CHINESE_NUMBERS.items(), key=lambda item: -len(item[0])):
        if re.search(rf"{word}\s*(?:个|项|条|道)?\s*(?:任务|节点)", text):
            return value
    if "全部" in text and "玩法" in text:
        return 8
    if "完整" in text and any(word in text for word in ("主线", "流程", "入门", "进阶", "精通")):
        return 4
    return 0


@dataclass
class AcceptanceCriterion:
    kind: str
    label: str
    target: int = 0
    value: str = ""
    passed: bool = False
    detail: str = "尚未检查"


@dataclass
class AgentRunPlan:
    request: str
    baseline: dict
    steps: list[dict]
    criteria: list[AcceptanceCriterion]
    phase: str = "planned"
    attempts: int = 0
    failures: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict | None) -> "AgentRunPlan | None":
        if not isinstance(value, dict) or not value.get("request"):
            return None
        criteria = [
            AcceptanceCriterion(**item)
            for item in value.get("criteria", []) if isinstance(item, dict)
        ]
        return cls(
            request=str(value["request"]),
            baseline=dict(value.get("baseline", {})),
            steps=list(value.get("steps", [])),
            criteria=criteria,
            phase=str(value.get("phase", "planned")),
            attempts=int(value.get("attempts", 0) or 0),
            failures=[str(item) for item in value.get("failures", [])],
            actions=[str(item) for item in value.get("actions", [])][-200:],
        )

    def record_action(self, name: str) -> None:
        self.actions.append(str(name))
        self.actions = self.actions[-200:]

    def instructions(self) -> str:
        checks = "\n".join(f"- {item.label}" for item in self.criteria) or "- 保持项目结构有效"
        return (
            "本轮执行计划：\n"
            "1. 阅读当前项目与相关 Skill\n"
            "2. 使用最少且合适的工具完成修改\n"
            "3. 读取修改结果并进行结构检查\n"
            f"验收条件：\n{checks}\n"
            "在所有验收条件满足前，不得声称任务已经完成。"
        )

    def evaluate(self, store, issues: list[dict], mutation_actions: list[str]) -> list[str]:
        current = _metrics(store)
        new_ids = set(current["quest_ids"]) - set(self.baseline.get("quest_ids", []))
        error_count = sum(1 for issue in issues if issue.get("severity") == "error")
        failures = []
        for criterion in self.criteria:
            if criterion.kind == "mutation":
                actual = len(mutation_actions)
                criterion.passed = actual > 0
                criterion.detail = f"已执行 {actual} 次修改"
            elif criterion.kind == "chapters_added":
                actual = current["chapter_count"] - int(self.baseline.get("chapter_count", 0))
                criterion.passed = actual >= criterion.target
                criterion.detail = f"已新增 {actual}/{criterion.target} 个章节"
            elif criterion.kind == "quests_added":
                actual = current["quest_count"] - int(self.baseline.get("quest_count", 0))
                criterion.passed = actual >= criterion.target
                criterion.detail = f"已新增 {actual}/{criterion.target} 个任务"
            elif criterion.kind == "dependencies_added":
                actual = current["dependency_count"] - int(self.baseline.get("dependency_count", 0))
                criterion.passed = actual >= criterion.target
                criterion.detail = f"已新增 {actual}/{criterion.target} 条依赖"
            elif criterion.kind == "row_wrap":
                rows = {}
                for chapter in store.project.chapters:
                    for quest in chapter.quests:
                        if quest.id in new_ids:
                            rows.setdefault(round(float(quest.y), 2), 0)
                            rows[round(float(quest.y), 2)] += 1
                expected_rows = max(1, (len(new_ids) + criterion.target - 1) // criterion.target)
                criterion.passed = len(rows) >= expected_rows and all(
                    count <= criterion.target for count in rows.values()
                )
                criterion.detail = f"实际 {len(rows)} 层，每层最多 {max(rows.values(), default=0)}/{criterion.target} 个"
            elif criterion.kind == "new_quests_typed":
                typed = 0
                for chapter in store.project.chapters:
                    for quest in chapter.quests:
                        if quest.id in new_ids and quest.tasks and quest.tasks[0].type == criterion.value:
                            typed += 1
                criterion.passed = typed >= criterion.target
                criterion.detail = f"匹配任务类型 {typed}/{criterion.target}"
            elif criterion.kind == "structure_valid":
                criterion.passed = error_count == 0
                criterion.detail = f"结构错误 {error_count} 个"
            if not criterion.passed:
                failures.append(f"{criterion.label}（{criterion.detail}）")
        self.failures = failures
        self.phase = "completed" if not failures else "needs_attention"
        for step in self.steps:
            if step.get("id") == "edit":
                step["status"] = "completed"
            elif step.get("id") == "verify":
                step["status"] = "completed" if not failures else "needs_attention"
        return failures


def build_run_plan(request: str, store) -> AgentRunPlan:
    text = str(request or "").strip()
    baseline = _metrics(store)
    mutation_intent = any(word in text for word in (
        "创建", "添加", "生成", "制作", "修改", "完善", "删除", "移动", "连线", "连接", "修复", "排列",
        "建议", "设计", "编写", "改进", "优化", "补全", "重排", "布局", "润色",
    ))
    creates_quests = any(word in text for word in (
        "创建", "添加", "生成", "制作", "安排", "新建", "建议", "设计", "编写",
    ))
    quest_count = _requested_quest_count(text) if creates_quests else 0
    wants_chapter = "章节" in text and any(word in text for word in (
        "创建", "添加", "生成", "制作", "新建", "建议", "设计", "编写",
    ))
    rejects_links = any(word in text for word in ("不要连线", "无需连线", "不需要连线", "独立任务"))
    wants_links = not rejects_links and any(word in text for word in (
        "主线", "流程", "连线", "连接", "前置", "依赖", "入门到", "进阶", "精通", "分支", "汇合",
    ))
    criteria = []
    if mutation_intent:
        criteria.append(AcceptanceCriterion("mutation", "至少产生一项实际修改", 1))
    if wants_chapter:
        criteria.append(AcceptanceCriterion("chapters_added", "创建所要求的章节", 1))
    if quest_count:
        criteria.append(AcceptanceCriterion("quests_added", f"新增至少 {quest_count} 个任务", quest_count))
    type_mentions = [
        (type_id, label) for type_id, label, words in (
            ("checkmark", "勾选", ("手动勾选", "勾选任务")),
            ("kill", "击杀", ("击杀任务", "击杀生物", "击杀")),
            ("dimension", "维度", ("维度任务", "访问维度", "进入维度")),
            ("item", "物品", ("物品任务", "提交物品", "检测物品")),
            ("advancement", "进度", ("进度任务", "游戏进度", "成就任务")),
        )
        if any(word in text for word in words)
    ]
    for type_id, label in type_mentions:
        target = quest_count if quest_count and len(type_mentions) == 1 else 1
        criteria.append(AcceptanceCriterion(
            "new_quests_typed", f"至少 {target} 个新增任务使用{label}条件", target, type_id,
        ))
    if wants_links:
        edge_target = max(1, quest_count - 1) if quest_count else 1
        criteria.append(AcceptanceCriterion("dependencies_added", f"建立至少 {edge_target} 条有效前置关系", edge_target))
    row_match = re.search(r"(?:每行|每层)\s*(\d{1,2})", text)
    if row_match is None:
        row_match = re.search(r"(\d{1,2})\s*(?:个任务|个)?后.{0,8}(?:下一层|下一行|换行)", text)
    row_width = int(row_match.group(1)) if row_match else 0
    if not row_width and quest_count > 5 and any(word in text for word in ("不要横向", "下一层", "下一行", "换行")):
        row_width = 5
    if row_width and quest_count > row_width:
        criteria.append(AcceptanceCriterion(
            "row_wrap", f"任务布局每层不超过 {row_width} 个", row_width,
        ))
    criteria.append(AcceptanceCriterion("structure_valid", "项目不能出现新的结构错误", 0))
    return AgentRunPlan(
        request=text,
        baseline=baseline,
        steps=[
            {"id": "inspect", "title": "理解项目和要求", "status": "pending"},
            {"id": "edit", "title": "调用工具执行修改", "status": "pending"},
            {"id": "verify", "title": "对照要求验收结果", "status": "pending"},
        ],
        criteria=criteria,
    )
