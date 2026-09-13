"""Product-level UX shell for AutoFTBQ Studio.

This module deliberately wraps the existing v2 editor instead of duplicating its
editing, Agent, persistence, or game-bridge logic.  It owns progressive
disclosure, first-run onboarding, discoverability affordances, and crash UX.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ai_providers import CUSTOM_PROVIDER
from . import ui as legacy_ui
from .bridge import StudioBridgeServer
from .editor.canvas_items import QuestNode
from .infrastructure.ai_setup import AISetupDialog
from .infrastructure.app_logging import configure_logging


class SimplifiedAISetupDialog(AISetupDialog):
    """Keep the common AI setup path short while preserving every advanced field."""

    def __init__(self, config_path: str, required: bool = False, parent=None):
        super().__init__(config_path, required=required, parent=parent)
        self.setWindowTitle("连接 AI")
        self._advanced_fields = (self.api_url, self.reasoning_effort, self.image_input)
        self._ai_form = self._find_form_layout()

        self.advanced_toggle = QToolButton(self)
        self.advanced_toggle.setText("高级设置 ▾")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolTip("API 地址、推理强度与多模态能力")
        self.advanced_toggle.toggled.connect(self._apply_advanced_visibility)
        self.layout().insertWidget(max(0, self.layout().count() - 2), self.advanced_toggle)

        self.provider.currentIndexChanged.connect(self._provider_may_require_advanced)
        self._apply_advanced_visibility(False)

    def _find_form_layout(self) -> QFormLayout | None:
        root = self.layout()
        for index in range(root.count()):
            child = root.itemAt(index).layout()
            if isinstance(child, QFormLayout):
                return child
        return None

    def _set_field_visible(self, widget: QWidget, visible: bool) -> None:
        widget.setVisible(visible)
        if self._ai_form is not None:
            label = self._ai_form.labelForField(widget)
            if label is not None:
                label.setVisible(visible)

    def _provider_may_require_advanced(self, *_args) -> None:
        if str(self.provider.currentData()) == CUSTOM_PROVIDER:
            self.advanced_toggle.setChecked(True)
        self._apply_advanced_visibility(self.advanced_toggle.isChecked())

    def _apply_advanced_visibility(self, visible: bool) -> None:
        forced = str(self.provider.currentData()) == CUSTOM_PROVIDER
        expanded = bool(visible or forced)
        for widget in self._advanced_fields:
            self._set_field_visible(widget, expanded)
        self.advanced_toggle.setText("高级设置 ▴" if expanded else "高级设置 ▾")
        if forced and not self.advanced_toggle.isChecked():
            self.advanced_toggle.blockSignals(True)
            self.advanced_toggle.setChecked(True)
            self.advanced_toggle.blockSignals(False)


class CommandPalette(QDialog):
    """Small searchable command launcher for features that do not need permanent buttons."""

    def __init__(self, commands: list[tuple[str, str, Callable[[], None]]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("AutoFTBQ 命令")
        self.setMinimumWidth(520)
        self.commands = commands

        layout = QVBoxLayout(self)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("输入操作名称，例如：检查、扫描、AI、任务…")
        self.results = QListWidget(self)
        layout.addWidget(self.search)
        layout.addWidget(self.results)

        self.search.textChanged.connect(self._refresh)
        self.results.itemActivated.connect(self._activate)
        self._refresh("")

    def _refresh(self, text: str) -> None:
        needle = str(text or "").strip().casefold()
        self.results.clear()
        for name, hint, callback in self.commands:
            haystack = f"{name} {hint}".casefold()
            if needle and needle not in haystack:
                continue
            item = QListWidgetItem(f"{name}\n{hint}")
            item.setData(Qt.ItemDataRole.UserRole, callback)
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def _activate(self, item: QListWidgetItem) -> None:
        callback = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        if callable(callback):
            callback()


class PolishedMainWindow(legacy_ui.MainWindow):
    """Progressively disclose the existing Studio without changing editor semantics."""

    SETTINGS_ORG = "AutoFTBQ"
    SETTINGS_APP = "Studio"

    def __init__(self, restore_workspace: bool = False, workspace_dir: str | None = None):
        self._settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        marker_root = workspace_dir or os.path.join(legacy_ui.ROOT_DIR, ".autoftbq_workspace")
        os.makedirs(marker_root, exist_ok=True)
        self._run_marker_path = os.path.join(marker_root, ".studio_running")
        self._previous_unclean_exit = os.path.exists(self._run_marker_path)
        try:
            with open(self._run_marker_path, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
        except OSError:
            self._run_marker_path = ""

        super().__init__(restore_workspace=restore_workspace, workspace_dir=workspace_dir)
        self._advanced_mode = self._settings.value("ux/advanced_mode", False, type=bool)
        self._install_welcome_page()
        self._install_mode_switch()
        self._simplify_canvas_toolbar()
        self._install_canvas_context_menu()
        self._install_command_palette()
        self._install_home_button()
        self._apply_mode_visibility()
        self.update_agent_context_ui()

        first_run = not self._settings.value("ux/welcome_seen", False, type=bool)
        if first_run:
            self.show_welcome()
        else:
            self.show_workspace()
        if self._previous_unclean_exit:
            QTimer.singleShot(150, self._show_recovery_notice)

    # ----- Onboarding -------------------------------------------------
    def _install_welcome_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("welcomePage")
        outer = QHBoxLayout(page)
        outer.setContentsMargins(70, 50, 70, 50)
        outer.addStretch(1)

        card = QFrame(page)
        card.setObjectName("welcomeCard")
        card.setMaximumWidth(760)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(38, 34, 38, 34)
        layout.setSpacing(14)

        eyebrow = QLabel("AUTOFTBQ STUDIO")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("从你现在要做的事开始")
        title.setStyleSheet("font-size: 28px; font-weight: 800; color: #202a24;")
        intro = QLabel(
            "无需先理解 SNBT、Schema 或 Agent 工具。打开任务书、创建新项目，"
            "或者让 Minecraft Agent Mod 连接进来即可。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #59645d; font-size: 13px;")
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(intro)

        self.continue_button = QPushButton("继续上次工作")
        self.continue_button.setObjectName("agentButton")
        self.continue_button.setEnabled(bool(self._workspace_restored))
        self.continue_button.clicked.connect(self.show_workspace)
        new_button = QPushButton("创建新任务书")
        new_button.clicked.connect(self._welcome_new_project)
        open_button = QPushButton("打开已有项目")
        open_button.clicked.connect(self._welcome_open_project)
        game_button = QPushButton("连接 Minecraft")
        game_button.clicked.connect(self._explain_game_connection)
        ai_button = QPushButton("配置 AI Agent")
        ai_button.clicked.connect(lambda: self.open_ai_setup(required=False))

        layout.addSpacing(6)
        for button in (self.continue_button, open_button, new_button, game_button, ai_button):
            button.setMinimumHeight(42)
            layout.addWidget(button)

        note = QLabel("提示：基础模式会隐藏少用的 FTBQ 字段；之后可随时切换到高级模式。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #6a746e; font-size: 11px; margin-top: 8px;")
        layout.addWidget(note)
        outer.addWidget(card, 1)
        outer.addStretch(1)
        self.workspace_modes.addWidget(page)
        self.welcome_page = page

        page.setStyleSheet("""
            #welcomePage { background: #ece9e1; }
            #welcomeCard { background: #fbfaf6; border: 1px solid #d5d0c5; border-radius: 16px; }
            #welcomeCard QPushButton { text-align: left; padding: 10px 16px; }
            #welcomeCard #agentButton { background: #d7f05c; color: #1c251f; font-weight: 800; }
        """)

    def show_welcome(self) -> None:
        if self._game_backend_mode:
            return
        self.workspace_modes.setCurrentWidget(self.welcome_page)
        self.setWindowTitle("AutoFTBQ Studio · 首页")

    def show_workspace(self) -> None:
        self._settings.setValue("ux/welcome_seen", True)
        if not self._game_backend_mode:
            self.workspace_modes.setCurrentIndex(0)
            self.setWindowTitle("AutoFTBQ Studio")

    def _welcome_new_project(self) -> None:
        self.new_project()
        self.show_workspace()

    def _welcome_open_project(self) -> None:
        before_path = self.project_path
        before_store = self.store
        self.open_project()
        if self.project_path != before_path or self.store is not before_store:
            self.show_workspace()

    def _explain_game_connection(self) -> None:
        bridge = getattr(self, "bridge_server", None)
        if bridge is None:
            QMessageBox.information(
                self, "连接 Minecraft",
                "本地游戏桥尚未启动。桌面编辑仍可使用；可查看日志了解桥启动失败原因。",
            )
            return
        QMessageBox.information(
            self, "连接 Minecraft",
            "本地桥已经在等待连接。打开安装 AutoFTBQ Agent Mod 的 Minecraft 世界后，"
            "Studio 会自动切换到游戏后端模式，不需要手动填写端口。",
        )

    def _install_home_button(self) -> None:
        sidebar = self.findChild(QFrame, "sidebar")
        if sidebar is None or sidebar.layout() is None:
            return
        button = QPushButton("首页")
        button.setToolTip("回到开始页")
        button.clicked.connect(self.show_welcome)
        sidebar.layout().insertWidget(max(0, sidebar.layout().count() - 2), button)
        self.home_button = button

    # ----- Basic / advanced progressive disclosure -------------------
    def _install_mode_switch(self) -> None:
        main_area = self.findChild(QFrame, "mainArea")
        if main_area is None or main_area.layout() is None:
            return
        bar = QFrame(main_area)
        bar.setObjectName("modeBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 7, 10, 7)
        self.mode_label = QLabel()
        self.mode_toggle = QToolButton()
        self.mode_toggle.setCheckable(True)
        self.mode_toggle.setChecked(self._advanced_mode)
        self.mode_toggle.clicked.connect(self.set_advanced_mode)
        row.addWidget(self.mode_label)
        row.addStretch(1)
        row.addWidget(self.mode_toggle)
        main_area.layout().insertWidget(1, bar)
        bar.setStyleSheet(
            "#modeBar { background: #eef2ed; border: 1px solid #d5ddd7; border-radius: 8px; }"
        )

    @staticmethod
    def _set_tab_visible_by_text(tabs, text: str, visible: bool) -> None:
        for index in range(tabs.count()):
            if tabs.tabText(index) == text:
                tabs.setTabVisible(index, visible)
                return

    def set_advanced_mode(self, enabled: bool) -> None:
        self._advanced_mode = bool(enabled)
        self._settings.setValue("ux/advanced_mode", self._advanced_mode)
        if hasattr(self, "mode_toggle"):
            self.mode_toggle.setChecked(self._advanced_mode)
        self._apply_mode_visibility()

    def _apply_mode_visibility(self) -> None:
        advanced = bool(self._advanced_mode)
        self._set_tab_visible_by_text(self.editor_tabs, "任务书", advanced)
        self._set_tab_visible_by_text(self.task_tabs, "显示与推进", advanced)

        # Validation remains a first-class basic feature; only raw SNBT is advanced.
        expert_index = self.editor_tabs.indexOf(self.expert_tabs)
        if expert_index >= 0:
            self.editor_tabs.setTabVisible(expert_index, True)
            self.editor_tabs.setTabText(expert_index, "专家" if advanced else "检查")
        if self.expert_tabs.count():
            self.expert_tabs.setTabVisible(0, advanced)
            if not advanced and self.validation_tab_index >= 0:
                self.expert_tabs.setCurrentIndex(self.validation_tab_index)

        if hasattr(self, "mode_label"):
            self.mode_label.setText(
                "界面模式：高级 · 显示完整 FTBQ 字段与 SNBT"
                if advanced else "界面模式：基础 · 保留常用编辑、检查与 Agent"
            )
            self.mode_toggle.setText("切换到基础模式" if advanced else "切换到高级模式")

    # ----- Canvas discoverability / toolbar reduction ----------------
    def _simplify_canvas_toolbar(self) -> None:
        editor_layout = self.editor_panel.layout()
        toolbar = editor_layout.itemAt(0).layout() if editor_layout and editor_layout.count() > 0 else None
        actions = editor_layout.itemAt(1).layout() if editor_layout and editor_layout.count() > 1 else None
        if toolbar is not None:
            for index in range(toolbar.count()):
                widget = toolbar.itemAt(index).widget()
                if widget is not None and hasattr(widget, "text") and widget.text() in {"-", "+", "适应画布"}:
                    widget.hide()
        if actions is None:
            return
        for index in range(actions.count()):
            widget = actions.itemAt(index).widget()
            if widget is not None and hasattr(widget, "text") and widget.text() in {"复制", "粘贴", "删除"}:
                widget.hide()
        self.more_tools_button = QToolButton(self.editor_panel)
        self.more_tools_button.setText("更多 ▾")
        menu = QMenu(self.more_tools_button)
        self._add_menu_action(menu, "适应画布", self.fit_canvas)
        self._add_menu_action(menu, "放大", lambda: self.canvas.scale(1.2, 1.2))
        self._add_menu_action(menu, "缩小", lambda: self.canvas.scale(1 / 1.2, 1 / 1.2))
        menu.addSeparator()
        self._add_menu_action(menu, "复制所选", self.copy_canvas_selection, "Ctrl+C")
        self._add_menu_action(menu, "粘贴", self.paste_canvas_selection, "Ctrl+V")
        self._add_menu_action(menu, "删除所选", self.delete_canvas_selection, "Delete")
        self.more_tools_button.setMenu(menu)
        self.more_tools_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        actions.insertWidget(5, self.more_tools_button)

    @staticmethod
    def _add_menu_action(menu: QMenu, text: str, callback, shortcut: str = "") -> QAction:
        action = menu.addAction(text)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        return action

    def _install_canvas_context_menu(self) -> None:
        viewport = self.canvas.viewport()
        viewport.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        viewport.customContextMenuRequested.connect(self._show_canvas_context_menu)

    def _show_canvas_context_menu(self, point) -> None:
        item = self.canvas.itemAt(point)
        if isinstance(item, QuestNode):
            if not item.isSelected():
                self.scene.clearSelection()
                item.setSelected(True)
            self.current_quest_id = item.quest.id

        menu = QMenu(self)
        self._add_menu_action(menu, "添加任务", self.add_quest)
        selected_quests = [entry for entry in self.scene.selectedItems() if isinstance(entry, QuestNode)]
        if len(selected_quests) == 1:
            quest = selected_quests[0].quest
            label = (
                "取消 Agent 关注此任务"
                if quest.id in self.agent_context_quest_ids else "让 Agent 关注此任务"
            )
            self._add_menu_action(menu, label, lambda qid=quest.id: self.toggle_agent_quest_context(qid))
            self._add_menu_action(menu, "复制任务", self.copy_canvas_selection)
            menu.addSeparator()
        self._add_menu_action(menu, "粘贴", self.paste_canvas_selection)
        self._add_menu_action(menu, "适应画布", self.fit_canvas)
        if self.scene.selectedItems():
            self._add_menu_action(menu, "删除所选", self.delete_canvas_selection)
        menu.exec(self.canvas.viewport().mapToGlobal(point))

    def update_agent_context_ui(self) -> None:
        super().update_agent_context_ui()
        chapter_ids, quest_ids = self._valid_agent_context()
        names: list[str] = []
        for chapter in self.store.project.chapters:
            if chapter.id in chapter_ids:
                names.append(f"章 · {chapter.title}")
            for quest in chapter.quests:
                if quest.id in quest_ids:
                    names.append(quest.title)
        if not names:
            self.agent_context_label.setText("Agent 关注：未选择 · 右键任务，或 Alt + 点击")
            self.agent_context_label.setToolTip("选中范围后，Agent 会优先围绕这些章节或任务工作。")
            return
        visible = "  ".join(f"〔{name}〕" for name in names[:3])
        suffix = f"  +{len(names) - 3}" if len(names) > 3 else ""
        self.agent_context_label.setText(f"Agent 关注：{visible}{suffix}")
        self.agent_context_label.setToolTip("\n".join(names))

    # ----- Command palette -------------------------------------------
    def _install_command_palette(self) -> None:
        self.command_palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.command_palette_shortcut.activated.connect(self.show_command_palette)

    def show_command_palette(self) -> None:
        commands = [
            ("添加任务", "在当前章节创建任务", self.add_quest),
            ("检查任务书", "打开结构检查结果", self.show_validation),
            ("扫描整合包", "索引物品、配方和图标", self.scan_modpack),
            ("配置 AI", "服务商、API Key 和模型", lambda: self.open_ai_setup(required=False)),
            ("适应画布", "让当前章节内容适应视野", self.fit_canvas),
            ("新建任务书", "创建一个新的空白项目", self.new_project),
            ("打开项目", "打开 AutoFTBQ Studio 项目", self.open_project),
            (
                "切换界面模式",
                "基础 / 高级",
                lambda: self.set_advanced_mode(not self._advanced_mode),
            ),
        ]
        palette = CommandPalette(commands, self)
        palette.exec()

    # ----- Recovery UX -----------------------------------------------
    def _show_recovery_notice(self) -> None:
        if os.environ.get("QT_QPA_PLATFORM", "").casefold() == "offscreen":
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("已恢复上次工作")
        dialog.setIcon(QMessageBox.Icon.Information)
        restored = "最近的自动保存已恢复，可以继续编辑。" if self._workspace_restored else "可以继续使用 Studio。"
        dialog.setText("AutoFTBQ 上次似乎没有正常关闭。\n\n" + restored)
        continue_button = dialog.addButton("继续", QMessageBox.ButtonRole.AcceptRole)
        logs_button = dialog.addButton("打开日志文件夹", QMessageBox.ButtonRole.ActionRole)
        dialog.setDefaultButton(continue_button)
        dialog.exec()
        if dialog.clickedButton() is logs_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(legacy_ui.LOG_PATH)))

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        if event.isAccepted() and self._run_marker_path:
            try:
                os.remove(self._run_marker_path)
            except FileNotFoundError:
                pass
            except OSError:
                legacy_ui.LOGGER.exception("Unable to clear Studio run marker")


def _prepare_product_ui() -> None:
    # MainWindow.open_ai_setup resolves this global from autoftbq_v2.ui at call time.
    legacy_ui.AISetupDialog = SimplifiedAISetupDialog


def run_app() -> int:
    logger, log_path = configure_logging(legacy_ui.ROOT_DIR)
    legacy_ui.install_exception_hooks(logger)
    logger.info("Starting AutoFTBQ Studio UX shell; log=%s", log_path)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    legacy_ui.apply_light_palette(app)
    if not hasattr(app, "_autoftbq_form_wheel_filter"):
        app._autoftbq_form_wheel_filter = legacy_ui.FormWheelNavigationFilter(app)
        app.installEventFilter(app._autoftbq_form_wheel_filter)
    _prepare_product_ui()

    bridge = None
    try:
        bridge = StudioBridgeServer().start()
        logger.info("Game bridge listening on 127.0.0.1:%s", bridge.port)
    except OSError:
        logger.exception("Unable to start the local game bridge")

    window = PolishedMainWindow(restore_workspace=True)
    window.attach_game_bridge(bridge)
    window.show()
    try:
        return app.exec()
    finally:
        if bridge is not None:
            bridge.stop()


def smoke_test_app() -> int:
    logger, _log_path = configure_logging(legacy_ui.ROOT_DIR)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    legacy_ui.apply_light_palette(app)
    _prepare_product_ui()
    bridge = None
    window = None
    try:
        bridge = StudioBridgeServer().start()
        window = PolishedMainWindow(restore_workspace=False)
        window.attach_game_bridge(bridge)
        window.show()
        app.processEvents()
        ready = (
            window.windowTitle().startswith("AutoFTBQ Studio")
            and bridge.port > 0
            and hasattr(window, "welcome_page")
            and hasattr(window, "more_tools_button")
        )
        logger.info("Packaged UX startup smoke test: %s", "passed" if ready else "failed")
        return 0 if ready else 2
    except Exception:
        logger.exception("Packaged UX startup smoke test failed")
        return 3
    finally:
        if window is not None:
            window.close()
        if bridge is not None:
            bridge.stop()
