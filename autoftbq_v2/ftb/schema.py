"""Official FTB Quests authoring schema used by the v2 editor and agent.

The schema describes fields instead of coercing a complete SNBT document into a
small Python model. This lets the UI offer typed controls while unknown fields
from addons and newer FTB Quests versions remain untouched in the raw document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str = "string"
    default: Any = None
    choices: tuple[str, ...] = ()
    registry: str = ""


@dataclass(frozen=True)
class ObjectSpec:
    type_id: str
    label: str
    fields: tuple[FieldSpec, ...] = ()


COMMON_TASK_FIELDS = (
    FieldSpec("optional_task", "可选条件", "bool", False),
    FieldSpec("disable_toast", "禁用完成提示", "bool", False),
    FieldSpec("tags", "标签", "string_list"),
)

TASK_TYPES = {
    "item": ObjectSpec("item", "物品", (
        FieldSpec("item", "物品", "item_stack", registry="item"),
        FieldSpec("count", "数量", "long", 1),
        FieldSpec("consume_items", "提交时消耗", "tristate", "default", ("default", "true", "false")),
        FieldSpec("only_from_crafting", "仅接受合成所得", "tristate", "default", ("default", "true", "false")),
        FieldSpec("match_components", "组件匹配", "choice", "none", ("none", "fuzzy", "strict")),
        FieldSpec("task_screen_only", "仅任务界面检测", "bool", False),
    ) + COMMON_TASK_FIELDS),
    "custom": ObjectSpec("custom", "自定义", (
        FieldSpec("title", "标题"),
        FieldSpec("description", "描述", "string_list"),
        FieldSpec("icon", "图标", "icon"),
        FieldSpec("max_progress", "最大进度", "long", 1),
    ) + COMMON_TASK_FIELDS),
    "xp": ObjectSpec("xp", "经验", (
        FieldSpec("value", "经验数量", "long", 1),
        FieldSpec("points", "使用经验点", "bool", False),
    ) + COMMON_TASK_FIELDS),
    "dimension": ObjectSpec("dimension", "维度", (
        FieldSpec("dimension", "维度", "registry_id", registry="dimension"),
    ) + COMMON_TASK_FIELDS),
    "stat": ObjectSpec("stat", "统计", (
        FieldSpec("stat", "统计项", "registry_id", registry="stat"),
        FieldSpec("value", "目标值", "int", 1),
    ) + COMMON_TASK_FIELDS),
    "kill": ObjectSpec("kill", "击杀实体", (
        FieldSpec("entity", "实体", "registry_id", registry="entity"),
        FieldSpec("entityTypeTag", "实体标签", "registry_id", registry="entity_tag"),
        FieldSpec("value", "击杀数量", "long", 1),
        FieldSpec("custom_name", "自定义名称"),
        FieldSpec("nbt_filter", "NBT 过滤条件"),
    ) + COMMON_TASK_FIELDS),
    "location": ObjectSpec("location", "位置", (
        FieldSpec("dimension", "维度", "registry_id", registry="dimension"),
        FieldSpec("ignore_dimension", "忽略维度", "bool", False),
        FieldSpec("position", "中心坐标", "int_array"),
        FieldSpec("size", "区域大小", "int_array"),
    ) + COMMON_TASK_FIELDS),
    "checkmark": ObjectSpec("checkmark", "勾选", COMMON_TASK_FIELDS),
    "advancement": ObjectSpec("advancement", "进度", (
        FieldSpec("advancement", "进度", "registry_id", registry="advancement"),
        FieldSpec("criterion", "条件"),
    ) + COMMON_TASK_FIELDS),
    "observation": ObjectSpec("observation", "观察", (
        FieldSpec("to_observe", "观察目标"),
        FieldSpec("observation_type", "观察类型", "choice", "block", (
            "block", "block_tag", "block_state", "block_entity", "block_entity_type",
            "entity_type", "entity_type_tag",
        )),
        FieldSpec("observe_type", "旧版观察类型", "int", 0),
        FieldSpec("timer", "观察时间", "long", 20),
    ) + COMMON_TASK_FIELDS),
    "biome": ObjectSpec("biome", "群系", (
        FieldSpec("biome", "群系", "registry_id", registry="biome"),
    ) + COMMON_TASK_FIELDS),
    "structure": ObjectSpec("structure", "结构", (
        FieldSpec("structure", "结构", "registry_id", registry="structure"),
    ) + COMMON_TASK_FIELDS),
    "gamestage": ObjectSpec("gamestage", "游戏阶段", (
        FieldSpec("stage", "阶段"),
        FieldSpec("team_stage", "队伍阶段", "bool", False),
    ) + COMMON_TASK_FIELDS),
    "fluid": ObjectSpec("fluid", "流体", (
        FieldSpec("fluid", "流体", "fluid_stack", registry="fluid"),
    ) + COMMON_TASK_FIELDS),
    "forge_energy": ObjectSpec("forge_energy", "NeoForge 能量", (
        FieldSpec("value", "能量数量", "long", 1),
        FieldSpec("max_input", "单次最大输入", "long", 0),
    ) + COMMON_TASK_FIELDS),
    "tech_reborn_energy": ObjectSpec("tech_reborn_energy", "Fabric 能量", (
        FieldSpec("value", "能量数量", "long", 1),
        FieldSpec("max_input", "单次最大输入", "long", 0),
    ) + COMMON_TASK_FIELDS),
}

TASK_TYPE_CATEGORIES = {
    "item": "收集", "fluid": "收集", "xp": "收集",
    "forge_energy": "收集", "tech_reborn_energy": "收集",
    "dimension": "探索", "biome": "探索", "structure": "探索",
    "location": "探索", "observation": "探索", "advancement": "探索",
    "kill": "战斗",
    "stat": "进度", "gamestage": "进度",
    "checkmark": "手动", "custom": "扩展",
}

TASK_TYPE_DESCRIPTIONS = {
    "item": "检测或提交指定物品，可设置数量、消耗和匹配规则。",
    "fluid": "检测玩家提交的指定流体与容量。",
    "xp": "检测或提交玩家经验。",
    "forge_energy": "接收 NeoForge/Forge 能量。",
    "tech_reborn_energy": "接收 Fabric Tech Reborn 能量。",
    "dimension": "玩家进入指定维度后由 FTB Quests 自动完成。",
    "biome": "玩家进入指定群系后自动完成。",
    "structure": "玩家进入指定结构范围后自动完成。",
    "location": "玩家到达指定维度、中心坐标和区域大小后完成。",
    "observation": "玩家观察指定方块、实体或标签一段时间后完成。",
    "advancement": "玩家获得指定原版或模组进度后完成。",
    "kill": "玩家击杀指定实体或实体标签达到数量后完成。",
    "stat": "玩家的原版统计值达到目标后完成。",
    "gamestage": "检测外部 GameStage 阶段。",
    "checkmark": "由玩家在任务界面手动勾选完成。",
    "custom": "由命令、脚本或扩展模组自行推进。",
}

TASK_TYPE_DEFAULTS = {
    "dimension": {"dimension": "minecraft:overworld"},
    "kill": {"entity": "minecraft:zombie", "value": 1},
    "stat": {"stat": "minecraft:mob_kills", "value": 1},
    "xp": {"value": 1, "points": True},
    "location": {"dimension": "minecraft:overworld", "position": [0, 64, 0], "size": [16, 16, 16]},
    "fluid": {"fluid": {"id": "minecraft:water", "amount": 1000}},
    "forge_energy": {"value": 1000},
    "tech_reborn_energy": {"value": 1000},
}


COMMON_REWARD_FIELDS = (
    FieldSpec("team_reward", "队伍奖励", "tristate", "default", ("default", "true", "false")),
    FieldSpec("auto", "自动领取", "choice", "default", ("default", "enabled", "disabled", "invisible")),
    FieldSpec("exclude_from_claim_all", "从全部领取中排除", "bool", False),
    FieldSpec("ignore_reward_blocking", "忽略奖励阻塞", "bool", False),
    FieldSpec("disable_reward_screen_blur", "禁用奖励界面模糊", "bool", False),
    FieldSpec("disable_toast", "禁用完成提示", "bool", False),
    FieldSpec("tags", "标签", "string_list"),
)

REWARD_TYPES = {
    "item": ObjectSpec("item", "物品", (
        FieldSpec("item", "物品", "item_stack", registry="item"),
        FieldSpec("count", "数量", "int", 1),
        FieldSpec("random_bonus", "随机额外数量", "int", 0),
        FieldSpec("only_one", "只给予一种", "bool", False),
    ) + COMMON_REWARD_FIELDS),
    "choice": ObjectSpec("choice", "选择奖励", (
        FieldSpec("table_id", "奖励表", "object_id", registry="reward_table"),
    ) + COMMON_REWARD_FIELDS),
    "all_table": ObjectSpec("all_table", "奖励表全部内容", (
        FieldSpec("table_id", "奖励表", "object_id", registry="reward_table"),
    ) + COMMON_REWARD_FIELDS),
    "random": ObjectSpec("random", "随机奖励", (
        FieldSpec("table_id", "奖励表", "object_id", registry="reward_table"),
        FieldSpec("table_data", "内嵌奖励表", "compound"),
    ) + COMMON_REWARD_FIELDS),
    "loot": ObjectSpec("loot", "战利品", (
        FieldSpec("table_id", "奖励表", "object_id", registry="reward_table"),
        FieldSpec("table_data", "内嵌奖励表", "compound"),
    ) + COMMON_REWARD_FIELDS),
    "command": ObjectSpec("command", "命令", (
        FieldSpec("command", "命令"),
        FieldSpec("permission_level", "权限等级", "int", 2),
        FieldSpec("silent", "静默执行", "bool", False),
        FieldSpec("feedback_message", "反馈消息"),
    ) + COMMON_REWARD_FIELDS),
    "custom": ObjectSpec("custom", "自定义", (
        FieldSpec("title", "标题"),
        FieldSpec("description", "描述", "string_list"),
        FieldSpec("icon", "图标", "icon"),
    ) + COMMON_REWARD_FIELDS),
    "xp": ObjectSpec("xp", "经验点", (FieldSpec("xp", "经验点", "int", 1),) + COMMON_REWARD_FIELDS),
    "xp_levels": ObjectSpec("xp_levels", "经验等级", (FieldSpec("xp_levels", "等级", "int", 1),) + COMMON_REWARD_FIELDS),
    "advancement": ObjectSpec("advancement", "授予进度", (
        FieldSpec("advancement", "进度", "registry_id", registry="advancement"),
        FieldSpec("criterion", "条件"),
    ) + COMMON_REWARD_FIELDS),
    "toast": ObjectSpec("toast", "提示消息", (FieldSpec("description", "描述"),) + COMMON_REWARD_FIELDS),
    "gamestage": ObjectSpec("gamestage", "游戏阶段", (
        FieldSpec("stage", "阶段"),
        FieldSpec("remove", "移除阶段", "bool", False),
    ) + COMMON_REWARD_FIELDS),
    "currency": ObjectSpec("currency", "货币", (FieldSpec("amount", "数量", "int", 1),) + COMMON_REWARD_FIELDS),
}


QUEST_FIELDS = (
    FieldSpec("title", "标题"), FieldSpec("subtitle", "副标题"),
    FieldSpec("description", "描述", "string_list"), FieldSpec("icon", "图标", "icon"),
    FieldSpec("x", "X", "double", 0.0), FieldSpec("y", "Y", "double", 0.0),
    FieldSpec("shape", "形状"), FieldSpec("size", "节点大小", "double", 0.0),
    FieldSpec("icon_scale", "图标缩放", "double", 1.0), FieldSpec("optional", "可选任务", "bool", False),
    FieldSpec("invisible", "始终隐藏", "bool", False), FieldSpec("invisible_until_tasks", "完成若干条件后显示", "int", 0),
    FieldSpec("dependency_requirement", "前置规则", "choice", "all_completed", ("all_completed", "one_completed", "all_started", "one_started")),
    FieldSpec("min_required_dependencies", "最少前置数量", "int", 0),
    FieldSpec("dep_control_pts", "连线控制点", "compound"),
    FieldSpec("hide_dependency_lines", "隐藏前置连线", "tristate", "default", ("default", "true", "false")),
    FieldSpec("hide_dependent_lines", "隐藏后续连线", "bool", False),
    FieldSpec("disable_recipe_mod", "禁用配方查看", "tristate", "default", ("default", "true", "false")),
    FieldSpec("hide_until_deps_visible", "前置可见前隐藏", "tristate", "default", ("default", "true", "false")),
    FieldSpec("hide_until_deps_complete", "前置完成前隐藏", "tristate", "default", ("default", "true", "false")),
    FieldSpec("hide_text_until_complete", "完成前隐藏文本", "tristate", "default", ("default", "true", "false")),
    FieldSpec("can_repeat", "可重复", "tristate", "default", ("default", "true", "false")),
    FieldSpec("hide_details_until_startable", "可开始前隐藏详情", "tristate", "default", ("default", "true", "false")),
    FieldSpec("require_sequential_tasks", "条件按顺序完成", "tristate", "default", ("default", "true", "false")),
    FieldSpec("repeat_cooldown", "重复冷却", "int", 0),
    FieldSpec("max_completable_dependents", "最多可完成后续", "int", 0),
    FieldSpec("min_width", "最小面板宽度", "int", 0), FieldSpec("guide_page", "指南页面"),
    FieldSpec("progression_mode", "进度模式", "choice", "default", ("default", "flexible", "linear")),
    FieldSpec("hide_lock_icon", "隐藏锁图标", "bool", False),
    FieldSpec("ignore_reward_blocking", "忽略奖励阻塞", "bool", False),
    FieldSpec("disable_toast", "禁用完成提示", "bool", False),
    FieldSpec("tags", "标签", "string_list"),
    FieldSpec("preset", "视觉预设"),
)


CHAPTER_FIELDS = (
    FieldSpec("title", "标题"), FieldSpec("subtitle", "副标题"),
    FieldSpec("description", "描述", "string_list"), FieldSpec("icon", "图标", "icon"),
    FieldSpec("always_invisible", "始终隐藏", "bool", False),
    FieldSpec("default_quest_shape", "默认节点形状"), FieldSpec("default_quest_size", "默认节点大小", "double", 1.0),
    FieldSpec("default_hide_dependency_lines", "默认隐藏连线", "bool", False),
    FieldSpec("default_min_width", "默认面板宽度", "int", 0),
    FieldSpec("consume_items", "默认消耗物品", "tristate", "default", ("default", "true", "false")),
    FieldSpec("progression_mode", "进度模式", "choice", "default", ("default", "flexible", "linear")),
    FieldSpec("hide_quest_details_until_startable", "开始前隐藏详情", "bool", False),
    FieldSpec("hide_quest_until_deps_visible", "前置可见前隐藏任务", "bool", False),
    FieldSpec("hide_quest_until_deps_complete", "前置完成前隐藏任务", "bool", False),
    FieldSpec("hide_text_until_complete", "完成前隐藏文本", "bool", False),
    FieldSpec("default_repeatable_quest", "默认可重复", "bool", False),
    FieldSpec("require_sequential_tasks", "条件按顺序完成", "bool", False),
    FieldSpec("autofocus_id", "自动聚焦对象", "object_id"),
    FieldSpec("group", "章节分组", "object_id", registry="chapter_group"),
    FieldSpec("disable_toast", "禁用完成提示", "bool", False),
    FieldSpec("tags", "标签", "string_list"),
    FieldSpec("preset", "视觉预设"),
)


CHAPTER_GROUP_FIELDS = (
    FieldSpec("title", "标题"),
    FieldSpec("icon", "图标", "icon"),
    FieldSpec("tags", "标签", "string_list"),
)


REWARD_TABLE_FIELDS = (
    FieldSpec("title", "标题"),
    FieldSpec("icon", "图标", "icon"),
    FieldSpec("tags", "标签", "string_list"),
    FieldSpec("empty_weight", "空奖励权重", "double", 0.0),
    FieldSpec("loot_size", "抽取数量", "int", 1),
    FieldSpec("hide_tooltip", "隐藏提示", "bool", False),
    FieldSpec("use_title", "使用标题", "bool", False),
    FieldSpec("loot_crate", "战利品箱", "compound"),
    FieldSpec("loot_table_id", "战利品表 ID", "registry_id", registry="loot_table"),
)


CHAPTER_IMAGE_FIELDS = (
    FieldSpec("image", "图片资源"),
    FieldSpec("x", "X", "double", 0.0), FieldSpec("y", "Y", "double", 0.0),
    FieldSpec("width", "宽度", "double", 1.0), FieldSpec("height", "高度", "double", 1.0),
    FieldSpec("rotation", "旋转", "double", 0.0), FieldSpec("color", "颜色", "int"),
    FieldSpec("alpha", "透明度", "int", 255), FieldSpec("order", "层级", "int", 0),
    FieldSpec("click_action", "点击动作", "compound"), FieldSpec("click", "旧版点击动作"),
    FieldSpec("dev", "仅编辑者可见", "bool", False),
    FieldSpec("corner", "对齐画布角落", "bool", False),
    FieldSpec("dependency", "显示所需前置", "object_id"),
    FieldSpec("position_locked", "锁定位置", "bool", False),
    FieldSpec("text_on_image", "在图片上显示文字", "bool", False),
    FieldSpec("text_shadow", "文字阴影", "bool", False),
    FieldSpec("text_inset", "文字内边距", "int", 0),
    FieldSpec("text_h_align", "文字水平对齐", "choice", "center", ("left", "center", "right")),
    FieldSpec("text_v_align", "文字垂直对齐", "choice", "center", ("top", "center", "bottom")),
    FieldSpec("tags", "标签", "string_list"),
)


QUEST_LINK_FIELDS = (
    FieldSpec("linked_quest", "目标任务", "object_id", registry="quest"),
    FieldSpec("x", "X", "double", 0.0), FieldSpec("y", "Y", "double", 0.0),
    FieldSpec("shape", "形状"), FieldSpec("size", "大小", "double", 1.0),
)


BOOK_FIELDS = (
    FieldSpec("default_reward_team", "默认队伍共享奖励", "bool", False),
    FieldSpec("default_consume_items", "默认消耗物品", "bool", False),
    FieldSpec("default_autoclaim_rewards", "默认自动领取", "choice"),
    FieldSpec("default_quest_shape", "默认节点形状"),
    FieldSpec("default_quest_disable_jei", "默认禁用配方查看", "bool", False),
    FieldSpec("emergency_items", "紧急物品", "compound"),
    FieldSpec("emergency_items_cooldown", "紧急物品冷却", "int", 0),
    FieldSpec("drop_loot_crates", "掉落战利品箱", "bool", False),
    FieldSpec("loot_crate_no_drop", "战利品箱空掉落权重", "compound"),
    FieldSpec("disable_gui", "禁用任务界面", "bool", False),
    FieldSpec("grid_scale", "网格缩放", "double", 1.0),
    FieldSpec("pause_game", "打开界面时暂停", "bool", False),
    FieldSpec("lock_message", "锁定提示"), FieldSpec("progression_mode", "进度模式", "choice"),
    FieldSpec("detection_delay", "检测间隔", "int", 20), FieldSpec("show_lock_icons", "显示锁图标", "bool", False),
    FieldSpec("drop_book_on_death", "死亡掉落任务书", "bool", False),
    FieldSpec("hide_excluded_quests", "隐藏排除任务", "bool", False),
    FieldSpec("fallback_locale", "回退语言"), FieldSpec("verify_on_load", "加载时校验", "bool", False),
    FieldSpec("suppress_all_autoclaiming", "禁用全部自动领取", "bool", False),
    FieldSpec("presets", "视觉预设库", "compound"), FieldSpec("preset", "当前视觉预设"),
    FieldSpec("tags", "标签", "string_list"),
)


CORE_QUEST_SHAPES = ("circle", "square", "rsquare", "none")
DEFAULT_THEME_QUEST_SHAPES = ("diamond", "pentagon", "hexagon", "octagon", "heart", "gear")
CURRENT_FILE_VERSION = 13


def object_spec(kind: str, type_id: str) -> ObjectSpec:
    registry = TASK_TYPES if kind == "task" else REWARD_TYPES
    return registry.get(type_id, ObjectSpec(type_id, f"扩展类型：{type_id}"))


def schema_catalog() -> dict[str, Any]:
    def encode(spec: ObjectSpec) -> dict[str, Any]:
        return {
            "type": spec.type_id,
            "label": spec.label,
            "fields": [field.__dict__ for field in spec.fields],
        }

    return {
        "tasks": [encode(spec) for spec in TASK_TYPES.values()],
        "rewards": [encode(spec) for spec in REWARD_TYPES.values()],
        "quest_fields": [field.__dict__ for field in QUEST_FIELDS],
        "chapter_fields": [field.__dict__ for field in CHAPTER_FIELDS],
        "chapter_group_fields": [field.__dict__ for field in CHAPTER_GROUP_FIELDS],
        "reward_table_fields": [field.__dict__ for field in REWARD_TABLE_FIELDS],
        "chapter_image_fields": [field.__dict__ for field in CHAPTER_IMAGE_FIELDS],
        "quest_link_fields": [field.__dict__ for field in QUEST_LINK_FIELDS],
        "book_fields": [field.__dict__ for field in BOOK_FIELDS],
        "core_shapes": list(CORE_QUEST_SHAPES),
        "default_theme_shapes": list(DEFAULT_THEME_QUEST_SHAPES),
        "current_file_version": CURRENT_FILE_VERSION,
    }
