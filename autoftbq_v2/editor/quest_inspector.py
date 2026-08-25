"""View models and parsing helpers for the quest property inspector."""

from __future__ import annotations

from dataclasses import dataclass

from snbt_parser import parse_snbt, to_snbt

from ..ftb.schema import TASK_TYPES


@dataclass(frozen=True)
class QuestInspectorData:
    quest_id: str
    chapter_id: str
    title: str
    subtitle: str
    icon: str
    shape: str
    task_type: str
    target: str
    count: int
    description: str
    tasks_snbt: str
    rewards_snbt: str
    raw_properties: dict | None


def inspector_data(store, quest) -> QuestInspectorData:
    task = quest.tasks[0] if quest.tasks else None
    found = store.quest(quest.id)
    chapter_id = found[0].id if found is not None else ""
    if hasattr(store, "raw_sections"):
        tasks, rewards = store.raw_sections(quest.id)
    else:
        tasks = [
            {"type": item.type, "item": item.target, "count": item.count}
            for item in quest.tasks
        ]
        rewards = quest.rewards
    raw_properties = store.quest_data(quest.id) if hasattr(store, "quest_data") else None
    return QuestInspectorData(
        quest_id=quest.id,
        chapter_id=chapter_id,
        title=quest.title,
        subtitle=quest.subtitle,
        icon=quest.icon,
        shape=quest.shape,
        task_type=task.type if task else "checkmark",
        target=task.target if task else "",
        count=task.count if task else 1,
        description="\n".join(quest.description),
        tasks_snbt=to_snbt(tasks),
        rewards_snbt=to_snbt(rewards),
        raw_properties=raw_properties,
    )


def parse_sections(tasks_text: str, rewards_text: str) -> tuple[object, object]:
    return parse_snbt(tasks_text or "[]"), parse_snbt(rewards_text or "[]")


def condition_summary(quest) -> str:
    count = len(quest.tasks)
    if not count:
        return "尚未设置完成条件"
    labels = []
    for task in quest.tasks[:3]:
        spec = TASK_TYPES.get(task.type)
        label = spec.label if spec else task.type
        labels.append(f"{label}：{task.target or '待设置'}")
    suffix = f"，另有 {count - 3} 条" if count > 3 else ""
    return f"共 {count} 条：" + "；".join(labels) + suffix
