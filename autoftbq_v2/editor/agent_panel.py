"""Agent workspace panel with no project or persistence responsibilities."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
)


class AgentPanel(QFrame):
    """Presentation-only Agent panel used by the main workspace."""

    send_requested = Signal()
    setup_requested = Signal()
    clear_context_requested = Signal()
    command_selected = Signal(str)
    open_game_book_requested = Signal()
    sync_game_book_requested = Signal()

    def __init__(self, commands, parent=None):
        super().__init__(parent)
        self.setObjectName("agentPanel")
        self.setMinimumWidth(290)
        self.setMaximumWidth(410)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("Agent")
        title.setObjectName("agentTitle")
        self.agent_state = QLabel("待命")
        self.agent_state.setObjectName("statusPill")
        self.ai_setup_button = QPushButton("AI 配置")
        self.ai_setup_button.clicked.connect(self.setup_requested)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.ai_setup_button)
        title_row.addWidget(self.agent_state)
        layout.addLayout(title_row)

        self.model_label = QLabel("尚未配置 AI；离线编辑功能仍可使用")
        self.model_label.setObjectName("agentMuted")
        self.model_label.setWordWrap(True)
        layout.addWidget(self.model_label)

        self.game_bridge_label = QLabel("游戏连接：等待 AutoFTBQ Agent Mod")
        self.game_bridge_label.setObjectName("agentMuted")
        self.game_bridge_label.setWordWrap(True)
        layout.addWidget(self.game_bridge_label)

        game_book_row = QHBoxLayout()
        self.open_game_book_button = QPushButton("在工作台编辑游戏任务书")
        self.open_game_book_button.setEnabled(False)
        self.open_game_book_button.clicked.connect(self.open_game_book_requested)
        self.sync_game_book_button = QPushButton("同步到游戏")
        self.sync_game_book_button.setEnabled(False)
        self.sync_game_book_button.clicked.connect(self.sync_game_book_requested)
        game_book_row.addWidget(self.open_game_book_button, 1)
        game_book_row.addWidget(self.sync_game_book_button)
        layout.addLayout(game_book_row)

        self.chat = QTextBrowser()
        self.chat.setObjectName("chat")
        self.chat.setOpenExternalLinks(True)
        layout.addWidget(self.chat, 3)

        progress_title = QLabel("Agent 进度")
        progress_title.setObjectName("sectionTitleLight")
        layout.addWidget(progress_title)
        self.agent_goal_label = QLabel("等待你的要求")
        self.agent_goal_label.setObjectName("agentGoal")
        self.agent_goal_label.setWordWrap(True)
        layout.addWidget(self.agent_goal_label)
        self.agent_progress_bar = QProgressBar()
        self.agent_progress_bar.setObjectName("agentProgress")
        self.set_progress_idle()
        layout.addWidget(self.agent_progress_bar)
        self.agent_current_label = QLabel("当前：等待开始")
        self.agent_current_label.setObjectName("agentCurrent")
        self.agent_current_label.setWordWrap(True)
        layout.addWidget(self.agent_current_label)
        self.agent_progress_list = QListWidget()
        self.agent_progress_list.setObjectName("agentProgressList")
        self.agent_progress_list.setMaximumHeight(125)
        self.agent_progress_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.agent_progress_list)

        progress_controls = QHBoxLayout()
        self.undo_checkpoint_button = QPushButton("撤销上一步")
        self.undo_checkpoint_button.setObjectName("checkpointButton")
        self.undo_checkpoint_button.setEnabled(False)
        self.action_toggle_button = QPushButton("技术详情")
        self.action_toggle_button.setObjectName("contextClear")
        self.action_toggle_button.setCheckable(True)
        self.action_toggle_button.toggled.connect(self.toggle_action_details)
        progress_controls.addWidget(self.undo_checkpoint_button)
        progress_controls.addStretch()
        progress_controls.addWidget(self.action_toggle_button)
        layout.addLayout(progress_controls)

        self.action_list = QListWidget()
        self.action_list.setMaximumHeight(125)
        self.action_list.setObjectName("actionList")
        self.action_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.action_list.hide()
        layout.addWidget(self.action_list)

        context_row = QHBoxLayout()
        self.agent_context_label = QLabel("上下文：未选择 · Alt + 点击任务或章节")
        self.agent_context_label.setObjectName("agentContext")
        self.agent_context_label.setWordWrap(True)
        self.clear_agent_context_button = QPushButton("清除")
        self.clear_agent_context_button.setObjectName("contextClear")
        self.clear_agent_context_button.clicked.connect(self.clear_context_requested)
        self.clear_agent_context_button.hide()
        context_row.addWidget(self.agent_context_label, 1)
        context_row.addWidget(self.clear_agent_context_button)
        layout.addLayout(context_row)

        self.prompt = QTextEdit()
        self.prompt.setObjectName("prompt")
        self.prompt.setPlaceholderText(
            "例如：为机械动力创建一个入门章节，先查询真实物品，再添加 5 个任务并检查结果。"
        )
        self.prompt.setMaximumHeight(110)
        layout.addWidget(self.prompt)

        self.send_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self.send_shortcut.activated.connect(self.send_requested)
        send_row = QHBoxLayout()
        self.command_button = QPushButton("/")
        self.command_button.setObjectName("commandButton")
        self.command_button.setToolTip("选择 Agent 指令")
        self.command_button.clicked.connect(self.show_command_menu)
        self.prompt_mode = QLabel("自动识别")
        self.prompt_mode.setObjectName("modePill")
        hint = QLabel("Ctrl + Enter 发送")
        hint.setObjectName("agentMuted")
        self.send_button = QPushButton("交给 Agent")
        self.send_button.setObjectName("agentButton")
        self.send_button.clicked.connect(self.send_requested)
        send_row.addWidget(self.command_button)
        send_row.addWidget(self.prompt_mode)
        send_row.addWidget(hint)
        send_row.addStretch()
        send_row.addWidget(self.send_button)
        layout.addLayout(send_row)

        self.command_menu = QMenu(self)
        for command, _intent, description in commands:
            action = self.command_menu.addAction(f"{command}  ·  {description}")
            action.triggered.connect(
                lambda _checked=False, value=command: self.command_selected.emit(value)
            )

    def show_command_menu(self) -> None:
        self.command_menu.popup(self.command_button.mapToGlobal(self.command_button.rect().bottomLeft()))

    def toggle_action_details(self, visible: bool) -> None:
        self.action_list.setVisible(bool(visible))
        self.action_toggle_button.setText("收起详情" if visible else "技术详情")

    def _progress_item(self, text: str, tooltip: str = "") -> QListWidgetItem:
        item = QListWidgetItem(str(text))
        item.setToolTip(tooltip or str(text))
        self.agent_progress_list.addItem(item)
        self.agent_progress_list.scrollToBottom()
        while self.agent_progress_list.count() > 30:
            self.agent_progress_list.takeItem(0)
        return item

    def update_progress(self, name: str, detail: str) -> None:
        try:
            value = json.loads(detail)
        except (TypeError, ValueError):
            value = {}
        operation_labels = {
            "get_project_summary": "读取任务书概况",
            "get_chapter_quests": "读取章节与任务 ID",
            "get_quest_sections": "读取任务条件与奖励",
            "get_ftb_schema": "查询 FTB 字段规则",
            "search_items": "查询整合包物品 ID",
            "search_registry": "查询游戏注册表 ID",
            "get_recipe": "查询合成配方",
            "create_chapter": "创建章节",
            "add_quest": "创建任务",
            "add_quest_chain": "批量创建任务链",
            "add_quest_object": "添加任务条件或奖励",
            "update_quest_object": "修正任务条件或奖励",
            "apply_dependency_plan": "规划任务连线",
            "validate_project": "执行本地结构检查",
        }
        if name in operation_labels:
            self.agent_current_label.setText(f"当前：{operation_labels[name]}")
        if name == "agent_plan":
            self.agent_progress_list.clear()
            goal = str(value.get("request") or "执行当前要求") if isinstance(value, dict) else "执行当前要求"
            self.agent_goal_label.setText(goal)
            self.agent_progress_bar.setRange(0, 3)
            self.agent_progress_bar.setValue(1)
            self.agent_progress_bar.setFormat("步骤 1/3 · 分析与规划")
            self.agent_current_label.setText("当前：读取项目并规划执行步骤")
            self._progress_item("完成 · 已分析要求并建立计划")
        elif name == "agent_checkpoint":
            label = str(value.get("label") or "已保存安全检查点") if isinstance(value, dict) else "已保存安全检查点"
            index = int(value.get("index", 0) or 0) if isinstance(value, dict) else 0
            self.agent_progress_bar.setRange(0, 3)
            self.agent_progress_bar.setValue(2)
            self.agent_progress_bar.setFormat(f"步骤 2/3 · 执行中 · 检查点 {index}")
            self.agent_current_label.setText(f"当前：{label}，继续下一步")
            self._progress_item(f"检查点 {index} · {label}", detail)
        elif name == "agent_tool_rejected":
            error = str(value.get("error") or "工具参数未通过检查") if isinstance(value, dict) else "工具参数未通过检查"
            self._progress_item(f"待修复 · {error}", detail)
            self.agent_progress_bar.setFormat("步骤 2/3 · 修正当前操作")
            self.agent_current_label.setText("当前：修改被安全拒绝，等待 Agent 修正参数")
        elif name == "agent_id_unverified":
            ids = value.get("ids", []) if isinstance(value, dict) else []
            labels = [str(entry.get("id", "")) for entry in ids if isinstance(entry, dict)]
            text = "、".join(value for value in labels if value) or "未知 ID"
            item = self._progress_item(f"提醒 · 未查询直接使用：{text}", detail)
            item.setForeground(QColor("#8a6400"))
        elif name == "agent_checkpoint_rollback":
            removed = str(value.get("removed") or "上一步") if isinstance(value, dict) else "上一步"
            self._progress_item(f"已撤销 · {removed}", detail)
        elif name == "agent_repair":
            self.agent_progress_bar.setRange(0, 0)
            self.agent_progress_bar.setFormat("正在修复验收缺口")
            self.agent_current_label.setText("当前：对照验收条件补齐缺口")
            self._progress_item("处理中 · 自动修复未完成项目")
        elif name == "agent_verify":
            passed = bool(value.get("passed")) if isinstance(value, dict) else False
            self.agent_progress_bar.setRange(0, 3)
            self.agent_progress_bar.setValue(3 if passed else 2)
            self.agent_progress_bar.setFormat("步骤 3/3 · 验收通过" if passed else "步骤 3/3 · 仍有待修复项")
            self.agent_current_label.setText("当前：本轮工作完成" if passed else "当前：等待继续修复")
            self._progress_item("完成 · 本地结构检查通过" if passed else "待继续 · 验收发现缺口", detail)
        elif name in {
            "create_chapter", "add_quest", "add_quest_chain", "update_quest",
            "replace_quest_sections", "add_quest_object", "update_quest_object",
            "move_quest", "connect_quests", "apply_dependency_plan", "disconnect_quests",
        }:
            self.agent_progress_bar.setRange(0, 0)
            self.agent_progress_bar.setFormat("正在执行修改")
        elif name == "agent_commit":
            self.set_progress_idle()
        elif name == "agent_rollback":
            self.set_progress_idle()

    def set_progress_idle(self) -> None:
        """Show an empty determinate bar whenever no Agent request is active."""
        self.agent_progress_bar.setRange(0, 100)
        self.agent_progress_bar.setValue(0)
        self.agent_progress_bar.setFormat("")
        if hasattr(self, "agent_current_label"):
            self.agent_current_label.setText("当前：等待下一条要求")

    def reset_progress(self) -> None:
        self.agent_progress_list.clear()
        self.agent_goal_label.setText("等待你的要求")
        self.set_progress_idle()
