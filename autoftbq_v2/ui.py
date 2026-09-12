"""PySide6 workspace for AutoFTBQ Studio."""

from __future__ import annotations

from html import escape
from copy import deepcopy
import json
import logging
import os
import secrets
import time

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPixmap, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from instance_resolver import application_dir
from quest_tools import QuestToolbox
from snbt_parser import to_snbt

from .editor.agent_panel import AgentPanel
from .agent_core.runtime import AgentReview, AgentRuntimeState, interrupted_run_message
from .agent_core.session import AgentSessionService
from .bridge import StudioBridgeServer
from .bridge.live_agent import LiveProjectAgentTask
from .editor.canvas_renderer import QuestCanvasRenderer
from .editor.icon_cache import IconPixmapCache
from .editor.canvas_items import (
    AgentContextChapterList, ChapterImageNode, CurvedDependencyLine, DependencyLine,
    FormWheelNavigationFilter, QuestCanvas, QuestLinkNode, QuestNode, apply_light_palette,
)
from .agent_core.requests import (
    COMMANDS,
    INTENT_LABELS,
    parse_request,
    prepare_request,
)
from .agent_core.item_policy import AgentItemPolicy
from .infrastructure.ai_setup import AISetupDialog, client_from_config, load_config, validate_ai_config
from .infrastructure.app_logging import LOGGER_NAME, configure_logging, install_exception_hooks
from .infrastructure.asset_index import AssetIndex
from .ftb.schema import BOOK_FIELDS, CHAPTER_FIELDS, QUEST_FIELDS
from .ftb_store import FTBQuestStore
from .editor.session import EditorSessionState
from .editor.commands import EditorProjectCommands
from .editor.quest_inspector import condition_summary, inspector_data, parse_sections
from .infrastructure.project_files import ProjectFileService
from .editor.quest_connections import QuestConnectionController
from .editor.picker_dialogs import IconPickerDialog, ItemPickerDialog, RegistryPickerDialog
from .editor.schema_editor import (
    ChapterCanvasObjectsEditor,
    ChapterGroupsEditor,
    CompoundPropertiesEditor,
    QuestSectionsEditor,
    RewardTablesEditor,
    TranslationsEditor,
)
from .infrastructure.workspace_session import WorkspaceSessionRepository
from .infrastructure.workspace_state import WorkspaceState
from .infrastructure.workers import (
    AgentWorker, CacheCleanupWorker, IconPrewarmWorker, ModpackScanWorker,
)

# Keep historical imports working while worker implementations live in the
# infrastructure module.
AgentThread = AgentWorker
ModpackScanThread = ModpackScanWorker


RESOURCE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = application_dir(RESOURCE_DIR)
LOGGER = logging.getLogger(LOGGER_NAME)
LOG_PATH = os.path.join(ROOT_DIR, "logs", "autoftbq_v2.log")
PROJECT_FILTER = "AutoFTBQ Studio Project (*.autoftbq.json);;JSON (*.json)"
QUEST_SHAPES = (
    ("默认", ""),
    ("圆形", "circle"),
    ("方形", "square"),
    ("圆角方形", "rsquare"),
    ("无边框", "none"),
)
TASK_TYPES = (
    ("物品任务", "item"),
    ("勾选任务", "checkmark"),
    ("击杀任务", "kill"),
    ("维度任务", "dimension"),
    ("进度任务", "advancement"),
)
REGISTRY_LABELS = {
    "item": "物品", "dimension": "维度", "entity": "实体", "entity_tag": "实体标签",
    "biome": "群系", "structure": "结构", "advancement": "进度", "fluid": "流体",
    "fluid_tag": "流体标签", "stat": "统计项", "quest": "任务", "reward_table": "奖励表",
    "chapter_group": "章节分组", "loot_table": "战利品表",
}


class MainWindow(QMainWindow):
    def __init__(self, restore_workspace: bool = False, workspace_dir: str | None = None):
        super().__init__()
        self.workspace_dir = workspace_dir or os.path.join(ROOT_DIR, ".autoftbq_workspace")
        self.workspace_repository = WorkspaceSessionRepository(self.workspace_dir)
        self.workspace_project_path = self.workspace_repository.project_path
        self.workspace_session_path = self.workspace_repository.session_path
        self._workspace_enabled = bool(restore_workspace)
        self._workspace_ready = False
        self._workspace_restored = False
        self.chat_records: list[dict] = []
        self.action_records: list[dict] = []
        self._restored_agent_history: list[dict] = []
        self._restored_agent_run_state: dict = {}
        self._restored_agent_request_context: dict = {}
        self.agent_runtime = AgentRuntimeState()
        self.agent_session = AgentSessionService()
        self._restored_view: dict = {}
        self.last_modpack_folder = ""
        self.editor_session = EditorSessionState()
        self.store = self._starter_store()
        self.project_commands = EditorProjectCommands(lambda: self.store)
        self.project_files = ProjectFileService()
        self.connection_controller = QuestConnectionController(lambda: self.store)
        self.project_path = ""
        self.toolbox = QuestToolbox()
        self.asset_index = None
        self.agent = None
        self.agent_thread = None
        self.scan_thread = None
        self.icon_prewarm_thread = None
        self.cache_cleanup_thread = None
        self._automatic_scan = False
        self._scan_preserve_store = False
        self._scan_last_progress_at = 0.0
        self.current_chapter_id = ""
        self.current_quest_id = ""
        self.connect_mode = False
        self.agent_busy = False
        self.agent_write_controls = []
        self.agent_write_shortcuts = []
        self._agent_control_states = {}
        self._agent_shortcut_states = {}
        self._agent_attention_message = ""
        self.game_agent_task = None
        self._game_event_cursor = 0
        self._live_game_base_payload = None
        self._live_game_revision = ""
        self._live_game_pending_payload = None
        self._applying_shared_events = False
        self._shared_studio_request_ids: list[str] = []
        self.canvas_clipboard = None
        self._canvas_bounds_chapter_id = None
        self._loading_inspector = False
        self.icon_pixmap_cache = IconPixmapCache(max_entries=256, ttl_seconds=600)
        self.canvas_renderer = QuestCanvasRenderer(
            QuestNode, ChapterImageNode, QuestLinkNode, DependencyLine, CurvedDependencyLine,
        )
        self.ai_config_path = os.path.join(ROOT_DIR, "config.json")
        self.ai_configured = False
        if self._workspace_enabled:
            self._load_workspace_snapshot()
        self.setWindowTitle("AutoFTBQ Studio")
        self.resize(1460, 900)
        self.setMinimumSize(1100, 700)
        self._build_ui()
        self._apply_style()
        self.workspace_autosave = QTimer(self)
        self.workspace_autosave.setSingleShot(True)
        self.workspace_autosave.setInterval(900)
        self.workspace_autosave.timeout.connect(self._save_workspace_snapshot)
        self.icon_memory_cleanup = QTimer(self)
        self.icon_memory_cleanup.setInterval(60_000)
        self.icon_memory_cleanup.timeout.connect(self.icon_pixmap_cache.cleanup)
        self.icon_memory_cleanup.start()
        self.icon_disk_cleanup = QTimer(self)
        self.icon_disk_cleanup.setInterval(30 * 60_000)
        self.icon_disk_cleanup.timeout.connect(self._start_cache_cleanup)
        self.icon_disk_cleanup.start()
        self.prompt.textChanged.connect(self.schedule_workspace_save)
        self.canvas.view_changed.connect(self.schedule_workspace_save)
        self.refresh_all()
        self._restore_workspace_ui()
        self.refresh_ai_state()
        self._workspace_ready = True
        if self._workspace_restored:
            self.statusBar().showMessage("已恢复上次未保存的工作区", 6000)
            QTimer.singleShot(100, self._restore_last_modpack)

    @property
    def agent_prompt_queue(self) -> list[str]:
        return self.agent_runtime.queue

    @agent_prompt_queue.setter
    def agent_prompt_queue(self, value) -> None:
        self.agent_runtime.queue = [str(item) for item in value][-self.agent_runtime.queue_limit:]

    @property
    def agent_busy(self) -> bool:
        return self.agent_runtime.busy

    @agent_busy.setter
    def agent_busy(self, value: bool) -> None:
        self.agent_runtime.busy = bool(value)

    @property
    def agent_thread(self):
        return self.agent_runtime.worker

    @agent_thread.setter
    def agent_thread(self, value) -> None:
        self.agent_runtime.worker = value

    @property
    def current_chapter_id(self) -> str:
        return self.editor_session.current_chapter_id

    @current_chapter_id.setter
    def current_chapter_id(self, value: str) -> None:
        self.editor_session.current_chapter_id = str(value or "")

    @property
    def current_quest_id(self) -> str:
        return self.editor_session.current_quest_id

    @current_quest_id.setter
    def current_quest_id(self, value: str) -> None:
        self.editor_session.current_quest_id = str(value or "")

    @property
    def agent_context_chapter_ids(self) -> set[str]:
        return self.editor_session.agent_chapter_ids

    @agent_context_chapter_ids.setter
    def agent_context_chapter_ids(self, value) -> None:
        self.editor_session.agent_chapter_ids = {str(item) for item in value}

    @property
    def agent_context_quest_ids(self) -> set[str]:
        return self.editor_session.agent_quest_ids

    @agent_context_quest_ids.setter
    def agent_context_quest_ids(self, value) -> None:
        self.editor_session.agent_quest_ids = {str(item) for item in value}

    @staticmethod
    def _starter_store():
        return FTBQuestStore.create_new()

    def _build_ui(self):
        self._game_backend_mode = False
        self._backend_event_cursor = 0
        self._backend_conversation = ""
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())
        root_layout.addWidget(self._build_main_area(), 1)
        self.desktop_workspace = root
        self.workspace_modes = QStackedWidget()
        self.workspace_modes.addWidget(root)
        backend = QWidget()
        layout = QVBoxLayout(backend)
        layout.setContentsMargins(32, 28, 32, 28)
        title = QLabel("AutoFTBQ Studio · 游戏后端模式")
        title.setStyleSheet("font-size: 24px; font-weight: bold")
        layout.addWidget(title)
        hint = QLabel("请在游戏内 FTB Quests 窗口编辑任务书或向 Agent 提出要求。\n"
                      "修改由游戏服务器保存并实时刷新，可在游戏内撤销。离线工作台草稿已保留。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.backend_status = QLabel("等待游戏连接")
        self.backend_status.setWordWrap(True)
        layout.addWidget(self.backend_status)
        configure = QPushButton("模型配置")
        configure.clicked.connect(lambda: self.open_ai_setup())
        layout.addWidget(configure)
        self.backend_history = QTextBrowser()
        layout.addWidget(self.backend_history, 1)
        self.workspace_modes.addWidget(backend)
        self.setCentralWidget(self.workspace_modes)

    def _enter_game_backend_mode(self):
        if self._game_backend_mode:
            return
        self._save_workspace_snapshot()
        self._game_backend_mode = True
        self.desktop_workspace.setEnabled(False)
        self.workspace_modes.setCurrentIndex(1)
        self.setWindowTitle("AutoFTBQ Studio · 游戏后端模式")

    def _refresh_backend_history(self, service, value):
        conversation = str(value.get("conversation_id", ""))
        if conversation != self._backend_conversation:
            self._backend_conversation = conversation
            self._backend_event_cursor = 0
            self.backend_history.clear()
        session_id = value.get("session_id")
        if not session_id or not conversation:
            return
        for event in service.events(session_id, self._backend_event_cursor, 200):
            self._backend_event_cursor = max(self._backend_event_cursor, int(event["event_id"]))
            kind = str(event.get("kind", ""))
            payload = event.get("payload", {})
            if kind.startswith("chat."):
                label = "玩家" if kind == "chat.user" else "Agent"
                text = str(payload.get("text", ""))
            elif kind.startswith(("work.", "change.")):
                label = "工作记录"
                text = str(payload.get("message") or payload.get("summary") or payload.get("stage") or kind)
            else:
                continue
            self.backend_history.append(f"<b>{label}</b>：{escape(text)}")

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(248)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(12)

        brand_row = QHBoxLayout()
        logo = QLabel("A2")
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(42, 42)
        brand = QVBoxLayout()
        name = QLabel("AutoFTBQ\nStudio")
        name.setObjectName("brandName")
        branch = QLabel("v2 Agent Workspace")
        branch.setObjectName("sidebarMuted")
        brand.addWidget(name)
        brand.addWidget(branch)
        brand_row.addWidget(logo)
        brand_row.addLayout(brand)
        brand_row.addStretch()
        layout.addLayout(brand_row)

        project_label = QLabel("当前任务书")
        project_label.setObjectName("sidebarLabel")
        layout.addWidget(project_label)
        self.project_title = QLineEdit()
        self.project_title.setObjectName("sidebarProjectTitle")
        self.project_title.editingFinished.connect(self.save_project_title)
        layout.addWidget(self.project_title)
        self.agent_write_controls.append(self.project_title)

        project_buttons = QHBoxLayout()
        for text, callback in (("新建", self.new_project), ("打开", self.open_project), ("保存", self.save_project)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            project_buttons.addWidget(button)
            self.agent_write_controls.append(button)
        layout.addLayout(project_buttons)

        workspace_hint = QLabel(
            "整合包、章节、检查和 Agent 已集中到右侧任务书编辑工作台。"
        )
        workspace_hint.setObjectName("sidebarHint")
        workspace_hint.setWordWrap(True)
        layout.addWidget(workspace_hint)
        layout.addStretch()
        version = QLabel("v2 Agent Workspace")
        version.setObjectName("sidebarMuted")
        layout.addWidget(version)
        return sidebar

    def _build_main_area(self):
        panel = QFrame()
        panel.setObjectName("mainArea")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        eyebrow = QLabel("ACTIVE WORKSPACE")
        eyebrow.setObjectName("eyebrow")
        self.view_title = QLabel("任务书编辑工作台")
        self.view_title.setObjectName("viewTitle")
        titles.addWidget(eyebrow)
        titles.addWidget(self.view_title)
        header.addLayout(titles)
        header.addStretch()
        workspace_hint = QLabel("整合包资源 · 离线编辑 · Agent 协作")
        workspace_hint.setObjectName("mainMuted")
        header.addWidget(workspace_hint)
        layout.addLayout(header)

        workspace = QSplitter(Qt.Orientation.Horizontal)
        workspace.setObjectName("integratedWorkspace")
        workspace.setChildrenCollapsible(False)
        self.chapter_panel = self._build_chapter_panel()
        self.editor_panel = self._build_editor()
        workspace.addWidget(self.chapter_panel)
        workspace.addWidget(self.editor_panel)
        workspace.addWidget(self._build_agent_panel())
        workspace.setSizes([220, 720, 340])
        layout.addWidget(workspace, 1)
        self.workspace_splitter = workspace
        return panel

    def _build_chapter_panel(self):
        frame = QFrame()
        frame.setObjectName("sideCard")
        frame.setMinimumWidth(205)
        frame.setMaximumWidth(280)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 16, 14, 14)
        row = QHBoxLayout()
        label = QLabel("任务书章节")
        label.setObjectName("sectionTitle")
        add = QPushButton("+")
        add.setFixedWidth(34)
        add.clicked.connect(self.add_chapter)
        self.agent_write_controls.append(add)
        row.addWidget(label)
        row.addStretch()
        row.addWidget(add)
        layout.addLayout(row)
        self.chapter_list = AgentContextChapterList()
        self.chapter_list.setObjectName("workspaceChapters")
        self.chapter_list.currentItemChanged.connect(self.select_chapter)
        self.chapter_list.agent_context_requested.connect(
            lambda chapter_id: QTimer.singleShot(0, lambda: self.toggle_agent_chapter_context(chapter_id))
        )
        layout.addWidget(self.chapter_list, 1)
        chapter_actions = QHBoxLayout()
        for text, tip, callback in (
            ("↑", "章节上移", lambda: self.move_current_chapter(-1)),
            ("↓", "章节下移", lambda: self.move_current_chapter(1)),
            ("删除", "删除当前章节", self.remove_current_chapter),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(callback)
            chapter_actions.addWidget(button)
            self.agent_write_controls.append(button)
        layout.addLayout(chapter_actions)
        scan_title = QLabel("整合包资源")
        scan_title.setObjectName("sectionTitleSmall")
        layout.addWidget(scan_title)
        self.modpack_status = QLabel("尚未扫描整合包\n扫描后可搜索物品 ID、配方与图标")
        self.modpack_status.setWordWrap(True)
        self.modpack_status.setObjectName("muted")
        layout.addWidget(self.modpack_status)
        self.scan_button = QPushButton("选择并扫描整合包")
        self.scan_button.clicked.connect(self.scan_modpack)
        layout.addWidget(self.scan_button)
        self.agent_write_controls.append(self.scan_button)
        utilities = QHBoxLayout()
        validate = QPushButton("检查任务书")
        validate.clicked.connect(self.show_validation)
        export = QPushButton("导出 SNBT")
        export.clicked.connect(self.export_snbt)
        utilities.addWidget(validate)
        utilities.addWidget(export)
        layout.addLayout(utilities)
        return frame

    def _build_editor(self):
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.chapter_heading = QLabel("章节画布")
        self.chapter_heading.setObjectName("chapterHeading")
        toolbar.addWidget(self.chapter_heading)
        self.connection_hint = QLabel("空白处拖动画布 · 滚轮缩放")
        self.connection_hint.setObjectName("mainMuted")
        toolbar.addWidget(self.connection_hint)
        toolbar.addStretch()
        zoom_out = QPushButton("-")
        zoom_out.setFixedWidth(32)
        zoom_out.clicked.connect(lambda: self.canvas.scale(1 / 1.2, 1 / 1.2))
        zoom_in = QPushButton("+")
        zoom_in.setFixedWidth(32)
        zoom_in.clicked.connect(lambda: self.canvas.scale(1.2, 1.2))
        fit = QPushButton("适应画布")
        fit.clicked.connect(self.fit_canvas)
        self.connect_button = QPushButton("连线模式")
        self.connect_button.setCheckable(True)
        self.connect_button.toggled.connect(self.toggle_connect_mode)
        add = QPushButton("添加任务")
        add.clicked.connect(self.add_quest)
        copy_button = QToolButton()
        copy_button.setText("复制")
        copy_button.setToolTip("复制所选任务、图片或跳转（Ctrl+C）")
        copy_button.clicked.connect(self.copy_canvas_selection)
        paste_button = QToolButton()
        paste_button.setText("粘贴")
        paste_button.setToolTip("粘贴到当前视野中心（Ctrl+V）")
        paste_button.clicked.connect(self.paste_canvas_selection)
        delete_button = QToolButton()
        delete_button.setText("删除")
        delete_button.setToolTip("删除画布所选对象（Delete）")
        delete_button.clicked.connect(self.delete_canvas_selection)
        undo = QPushButton("撤销")
        undo.clicked.connect(self.undo)
        redo = QPushButton("重做")
        redo.clicked.connect(self.redo)
        self.agent_write_controls.extend([
            self.connect_button, add, paste_button, delete_button, undo, redo,
        ])
        toolbar.addWidget(zoom_out)
        toolbar.addWidget(zoom_in)
        toolbar.addWidget(fit)
        layout.addLayout(toolbar)
        edit_actions = QHBoxLayout()
        edit_actions.addWidget(self.connect_button)
        edit_actions.addWidget(add)
        edit_actions.addWidget(copy_button)
        edit_actions.addWidget(paste_button)
        edit_actions.addWidget(delete_button)
        edit_actions.addStretch()
        edit_actions.addWidget(undo)
        edit_actions.addWidget(redo)
        layout.addLayout(edit_actions)

        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self.select_canvas_quest)
        self.canvas = QuestCanvas(self.scene)
        self.canvas.agent_context_requested.connect(
            lambda quest_id: QTimer.singleShot(0, lambda: self.toggle_agent_quest_context(quest_id))
        )
        self.canvas.setObjectName("canvas")
        self.canvas.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.canvas.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.canvas_shortcuts = []
        for sequence, callback in (
            ("Ctrl+C", self.copy_canvas_selection),
            ("Ctrl+V", self.paste_canvas_selection),
            ("Ctrl+Shift+V", lambda: self.paste_canvas_selection(with_dependencies=False)),
            ("Ctrl+Alt+V", lambda: self.paste_canvas_selection(as_link=True)),
            ("Delete", self.delete_canvas_selection),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self.canvas)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self.canvas_shortcuts.append(shortcut)
            if sequence != "Ctrl+C":
                self.agent_write_shortcuts.append(shortcut)
        layout.addWidget(self.canvas, 3)

        self.editor_tabs = QTabWidget()
        self.editor_tabs.setMinimumHeight(400)
        self.editor_tabs.setMaximumHeight(440)
        task_basic = self._build_inspector()
        self.sections_editor = QuestSectionsEditor(self.pick_registry_value, self)
        self.sections_editor.changed.connect(self.sections_changed)
        self.quest_properties = CompoundPropertiesEditor(
            QUEST_FIELDS, self.pick_registry_value,
            protected=("id", "tasks", "rewards", "dependencies"), parent=self,
        )
        self.quest_properties.changed.connect(self.properties_changed)
        self.task_tabs = QTabWidget()
        self.task_tabs.addTab(task_basic, "基础信息")
        self.task_tabs.addTab(self.sections_editor, "完成条件与奖励")
        self.task_tabs.addTab(self.quest_properties, "显示与推进")
        self.editor_tabs.addTab(self.task_tabs, "任务")
        self.chapter_properties = CompoundPropertiesEditor(
            CHAPTER_FIELDS, self.pick_registry_value,
            protected=("id", "quests", "quest_links", "images"), parent=self,
        )
        self.chapter_properties.changed.connect(self.properties_changed)
        self.book_properties = CompoundPropertiesEditor(
            BOOK_FIELDS, self.pick_registry_value, protected=("version",), parent=self,
        )
        self.book_properties.changed.connect(self.properties_changed)
        self.chapter_groups_editor = ChapterGroupsEditor(self.pick_registry_value, self)
        self.chapter_groups_editor.changed.connect(self.properties_changed)
        self.reward_tables_editor = RewardTablesEditor(self.pick_registry_value, self)
        self.reward_tables_editor.changed.connect(self.properties_changed)
        self.chapter_objects_editor = ChapterCanvasObjectsEditor(self.pick_registry_value, self)
        self.chapter_objects_editor.changed.connect(self.properties_changed)
        self.chapter_tabs = QTabWidget()
        self.chapter_tabs.addTab(self.chapter_properties, "章节规则")
        self.chapter_tabs.addTab(self.chapter_objects_editor, "图片与跳转")
        self.editor_tabs.addTab(self.chapter_tabs, "章节")
        self.book_tabs = QTabWidget()
        self.book_tabs.addTab(self.book_properties, "全局规则")
        self.book_tabs.addTab(self.chapter_groups_editor, "章节分组")
        self.book_tabs.addTab(self.reward_tables_editor, "奖励表")
        self.translations_editor = TranslationsEditor(self)
        self.translations_editor.changed.connect(self.run_validation)
        self.book_tabs.addTab(self.translations_editor, "多语言")
        self.editor_tabs.addTab(self.book_tabs, "任务书")
        self.expert_tabs = QTabWidget()
        self.expert_tabs.addTab(self._build_raw_panel(), "任务与奖励 SNBT")
        self.validation_tab_index = self.expert_tabs.addTab(self._build_validation_panel(), "检查结果")
        self.editor_tabs.addTab(self.expert_tabs, "专家")
        layout.addWidget(self.editor_tabs, 2)
        return frame

    def _build_inspector(self):
        panel = QWidget()
        panel.setObjectName("inspectorPanel")
        form = QFormLayout(panel)
        form.setContentsMargins(18, 16, 18, 16)
        form.setVerticalSpacing(7)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.quest_title = QLineEdit()
        self.quest_subtitle = QLineEdit()
        self.quest_icon = QLineEdit()
        self.quest_icon.setPlaceholderText("留空时跟随首个完成条件")
        self.quest_icon.textChanged.connect(self.update_quest_icon_preview)
        self.quest_chapter = QComboBox()
        self.quest_chapter.activated.connect(self.move_selected_quest_to_chapter)
        self.quest_type = QComboBox()
        for label, value in TASK_TYPES:
            self.quest_type.addItem(label, value)
        self.quest_target = QLineEdit()
        self.quest_target.setPlaceholderText("可手动输入，或从整合包物品索引中选择")
        self.quest_target.textChanged.connect(self.update_target_preview)
        self.quest_count = QSpinBox()
        self.quest_count.setRange(1, 999999)
        self.quest_description = QTextEdit()
        self.quest_description.setMaximumHeight(76)
        self.quest_shape = QComboBox()
        for label, value in QUEST_SHAPES:
            self.quest_shape.addItem(label, value)
        self.quest_shape.setToolTip("基础形状来自 FTB Quests 本体；主题扩展形状会作为自定义值保留")
        form.addRow("标题", self.quest_title)
        form.addRow("副标题", self.quest_subtitle)
        icon_row = QWidget()
        icon_layout = QHBoxLayout(icon_row)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        self.quest_icon_preview = QLabel("无图标")
        self.quest_icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.quest_icon_preview.setFixedSize(38, 38)
        self.quest_icon_preview.setObjectName("questIconPreview")
        choose_icon = QPushButton("选择…")
        choose_icon.clicked.connect(self.choose_quest_icon)
        use_target_icon = QToolButton()
        use_target_icon.setText("使用条件物品")
        use_target_icon.setToolTip("把首个完成条件的目标物品设为任务图标")
        use_target_icon.clicked.connect(self.use_target_as_quest_icon)
        clear_icon = QToolButton()
        clear_icon.setText("清除")
        clear_icon.setToolTip("清除自定义图标，让 FTB Quests 使用默认显示")
        clear_icon.clicked.connect(self.clear_quest_icon)
        icon_layout.addWidget(self.quest_icon_preview)
        icon_layout.addWidget(self.quest_icon, 1)
        icon_layout.addWidget(choose_icon)
        icon_layout.addWidget(use_target_icon)
        icon_layout.addWidget(clear_icon)
        form.addRow("任务图标", icon_row)
        self.quest_target.textChanged.connect(self.update_quest_icon_preview)
        form.addRow("所属章节", self.quest_chapter)
        form.addRow("节点形状", self.quest_shape)
        self.target_icon_preview = QLabel("无图标")
        self.target_icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.target_icon_preview.setFixedSize(38, 38)
        self.target_icon_preview.setObjectName("targetIconPreview")
        self.condition_summary = QLabel("尚未设置完成条件")
        self.condition_summary.setObjectName("conditionSummary")
        self.condition_summary.setWordWrap(True)
        edit_conditions = QPushButton("编辑完成条件…")
        edit_conditions.clicked.connect(self.show_conditions_editor)
        condition_row = QWidget()
        condition_layout = QHBoxLayout(condition_row)
        condition_layout.setContentsMargins(0, 0, 0, 0)
        condition_layout.addWidget(self.condition_summary, 1)
        condition_layout.addWidget(edit_conditions)
        form.addRow("完成条件", condition_row)
        form.addRow("描述", self.quest_description)
        row = QWidget()
        buttons = QHBoxLayout(row)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.autosave_state = QLabel("修改会实时同步到画布")
        self.autosave_state.setObjectName("autosaveState")
        remove = QPushButton("删除任务")
        remove.setObjectName("dangerButton")
        remove.clicked.connect(self.remove_quest)
        buttons.addWidget(self.autosave_state)
        buttons.addWidget(remove)
        buttons.addStretch()
        form.addRow("", row)
        self.inspector_autosave = QTimer(self)
        self.inspector_autosave.setSingleShot(True)
        self.inspector_autosave.setInterval(300)
        self.inspector_autosave.timeout.connect(lambda: self.apply_quest_changes(False, True))
        for field in (self.quest_title, self.quest_subtitle, self.quest_icon):
            field.textEdited.connect(self.schedule_quest_autosave)
        self.quest_shape.currentIndexChanged.connect(self.schedule_quest_autosave)
        self.quest_description.textChanged.connect(self.schedule_quest_autosave)
        return panel

    def _build_raw_panel(self):
        panel = QWidget()
        panel.setObjectName("rawPanel")
        layout = QHBoxLayout(panel)
        tasks_column = QVBoxLayout()
        tasks_column.addWidget(QLabel("任务条件 SNBT（完整列表）"))
        self.quest_tasks_raw = QTextEdit()
        self.quest_tasks_raw.setPlaceholderText("选择任务后显示原始 tasks 列表")
        tasks_column.addWidget(self.quest_tasks_raw)
        rewards_column = QVBoxLayout()
        rewards_column.addWidget(QLabel("奖励 SNBT（完整列表）"))
        self.quest_rewards_raw = QTextEdit()
        self.quest_rewards_raw.setPlaceholderText("选择任务后显示原始 rewards 列表")
        rewards_column.addWidget(self.quest_rewards_raw)
        apply_raw = QPushButton("应用 SNBT 修改")
        apply_raw.setObjectName("primaryButton")
        apply_raw.clicked.connect(lambda: self.apply_quest_changes(True))
        rewards_column.addWidget(apply_raw)
        layout.addLayout(tasks_column, 1)
        layout.addLayout(rewards_column, 1)
        return panel

    def _build_validation_panel(self):
        panel = QWidget()
        panel.setObjectName("validationPanel")
        layout = QVBoxLayout(panel)
        row = QHBoxLayout()
        row.addWidget(QLabel("本地确定性检查，不消耗 Token"))
        row.addStretch()
        button = QPushButton("立即检查")
        button.clicked.connect(self.run_validation)
        row.addWidget(button)
        layout.addLayout(row)
        self.validation_list = QListWidget()
        layout.addWidget(self.validation_list)
        return panel

    def _build_agent_panel(self):
        panel = AgentPanel(COMMANDS, self)
        panel.send_requested.connect(self.send_to_agent)
        panel.setup_requested.connect(self.open_ai_setup)
        panel.clear_context_requested.connect(self.clear_agent_context)
        panel.command_selected.connect(self.select_agent_command)
        panel.open_game_book_requested.connect(self.open_live_game_book)
        panel.sync_game_book_requested.connect(self.sync_live_game_book)
        panel.undo_checkpoint_button.clicked.connect(self.undo_agent_checkpoint)

        # Temporary compatibility aliases keep existing controllers and tests stable
        # while behavior moves out of MainWindow incrementally.
        self.agent_panel = panel
        for name in (
            "agent_state", "ai_setup_button", "model_label", "chat", "agent_goal_label",
            "game_bridge_label",
            "open_game_book_button", "sync_game_book_button",
            "agent_progress_bar", "agent_current_label", "agent_progress_list",
            "undo_checkpoint_button", "action_toggle_button", "action_list",
            "agent_context_label", "clear_agent_context_button", "prompt", "send_shortcut",
            "command_button", "prompt_mode", "send_button", "command_menu",
        ):
            setattr(self, name, getattr(panel, name))
        self.prompt.textChanged.connect(self._prompt_command_changed)
        if not self.chat_records:
            self.append_chat(
                "agent",
                "我是项目 Agent。先扫描整合包，然后告诉我想制作什么；执行进度与安全检查点会显示在下面。",
            )
        return panel

    def _apply_style(self):
        self.setStyleSheet("""
            * { font-family: 'Microsoft YaHei UI'; font-size: 13px; }
            QWidget { color: #202722; }
            QMainWindow, #mainArea { background: #f3f1eb; color: #202520; }
            #sidebar { background: #1d2824; color: #edf2ef; border: none; }
            #logo { background: #d7f05c; color: #1e2925; border-radius: 13px; font-size: 16px; font-weight: 800; }
            #brandName { color: white; font-size: 17px; font-weight: 800; }
            #sidebarMuted { color: #899b93; font-size: 10px; }
            #sidebarLabel { color: #a9b7b0; font-size: 11px; font-weight: 700; margin-top: 8px; }
            #sidebarHint { background: #263630; color: #c8d5cf; border: 1px solid #3b4b45; border-radius: 10px; padding: 14px; }
            #packCard { background: #263b33; border: 1px solid #527264; border-radius: 11px; }
            #packButton { background: #d7f05c; color: #1d2824; border: none; font-weight: 800; }
            #packStatus { color: #d5e2db; font-size: 10px; }
            #sidebarProjectTitle { background: #283630; color: white; border: 1px solid #3b4a44; font-size: 16px; font-weight: 700; padding: 9px; }
            #sidebar QPushButton { background: #283630; color: #dce5e0; border: 1px solid #3b4a44; }
            #sidebar QPushButton:hover { background: #34453e; border-color: #647c71; }
            #navButton { text-align: left; min-height: 45px; padding: 9px 12px; font-weight: 600; }
            #sidebarChapters { background: #202d28; color: #dce5e0; border: 1px solid #34443d; }
            #sidebarChapters::item:selected { background: #3b5148; color: white; }
            #eyebrow { color: #7b847c; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
            #viewTitle { color: #202520; font-size: 24px; font-weight: 800; }
            #mainMuted { color: #59645d; font-size: 10px; }
            #sectionTitle { color: #202a24; font-size: 16px; font-weight: 700; }
            #sectionTitleSmall { color: #445149; font-size: 11px; font-weight: 700; margin-top: 6px; }
            #chapterHeading { color: #202a24; font-size: 16px; font-weight: 700; }
            #sideCard, #agentPanel { background: #fbfaf6; border: 1px solid #d7d2c7; border-radius: 13px; }
            #sideCard #muted { color: #657169; font-size: 10px; }
            #agentTitle { color: #202a24; font-size: 18px; font-weight: 800; }
            #agentMuted { color: #657169; font-size: 10px; }
            #agentContext { background: #edf3d5; color: #405313; border: 1px solid #cbd99a; border-radius: 7px; padding: 6px; }
            #agentGoal { background: #edf2ee; color: #263c32; border-radius: 7px; padding: 7px; font-weight: 700; }
            #agentProgress { min-height: 16px; max-height: 16px; border: 1px solid #c9d2cc; border-radius: 7px; background: #e7e9e5; color: #263c32; text-align: center; font-size: 9px; }
            #agentProgress::chunk { background: #68a58b; border-radius: 6px; }
            #agentCurrent { color: #53625a; font-size: 10px; padding: 2px 4px; }
            #agentProgressList { background: #f4f3ee; color: #34433b; border: 1px solid #ddd8ce; padding: 3px; }
            #agentProgressList::item { padding: 4px 6px; }
            #checkpointButton { background: #e7f0eb; color: #245844; border-color: #bad0c5; padding: 5px 8px; }
            #contextClear, #commandButton { padding: 5px 8px; min-width: 24px; }
            #sectionTitleLight { color: #445149; font-size: 12px; font-weight: 700; }
            #conversationCard { background: #fbfaf6; border: 1px solid #d7d2c7; border-radius: 15px; }
            #composer { background: #fbfaf6; border: 1px solid #cfc9bd; border-radius: 15px; }
            #modePill { background: #e2eee8; color: #25644f; border-radius: 9px; padding: 4px 9px; font-size: 10px; }
            QPushButton { background: #faf8f2; color: #303730; border: 1px solid #d3cec3; border-radius: 8px; padding: 7px 12px; }
            QPushButton:hover { border-color: #778f82; background: white; }
            QPushButton:disabled, QToolButton:disabled { background: #e8e5dd; color: #68716c; border-color: #d1ccc2; }
            QToolButton { background: #faf8f2; color: #303730; border: 1px solid #d3cec3; border-radius: 7px; padding: 6px 9px; }
            QToolButton:hover { background: #fffefb; border-color: #778f82; }
            #primaryButton { background: #1f7059; color: white; border: none; }
            #primaryButton:disabled { background: #aeb9b3; color: #37413c; }
            #dangerButton { color: #a24639; }
            QListWidget, QLineEdit, QComboBox, QTextEdit, QSpinBox, QTextBrowser { background: #fbfaf6; color: #202722; border: 1px solid #d7d2c7; border-radius: 8px; padding: 7px; }
            QLineEdit, QComboBox, QSpinBox { min-height: 24px; padding: 5px 8px; }
            QLineEdit:disabled, QComboBox:disabled, QTextEdit:disabled, QSpinBox:disabled,
            QListWidget:disabled, QTextBrowser:disabled {
                background: #ebe8e0; color: #59635d; border-color: #d0cbc1;
            }
            QLabel:disabled { color: #68716c; }
            QComboBox::drop-down { width: 28px; border: none; }
            QComboBox QAbstractItemView { background: #fffefb; color: #202722; border: 1px solid #aaa498; outline: none; selection-background-color: #d4e8df; selection-color: #164f40; padding: 4px; }
            QListWidget::item { padding: 8px; border-radius: 6px; }
            QListWidget::item:selected { background: #d4e8df; color: #164f40; }
            #canvas { background: #e7e3da; border: 1px solid #d3cec2; border-radius: 12px; }
            QTabWidget::pane { border: 1px solid #d3cec2; border-radius: 8px; background: #f9f7f1; }
            #integratedWorkspace QTabWidget QLabel { color: #303a34; }
            #integratedWorkspace QScrollArea { background: #f9f7f1; border: none; }
            #schemaEditor, #schemaSidebar, #schemaSurface, #schemaScrollContent {
                background: #f9f7f1; color: #303a34;
            }
            #schemaEditor QLabel, #schemaSidebar QLabel, #schemaSurface QLabel, #schemaScrollContent QLabel {
                color: #303a34; background: transparent;
            }
            #schemaScroll, #schemaScrollViewport {
                background: #f9f7f1; color: #303a34; border: none;
            }
            #schemaEditor QListWidget, #schemaEditor QLineEdit, #schemaEditor QComboBox,
            #schemaEditor QTextEdit, #schemaEditor QSpinBox {
                background: #fffefb; color: #202722; border: 1px solid #cfc9bd;
            }
            #schemaEditor QListWidget::item { color: #303a34; }
            #schemaEditor QListWidget::item:selected {
                background: #d4e8df; color: #164f40;
            }
            #schemaEditor QComboBox QAbstractItemView {
                background: #fffefb; color: #202722;
                selection-background-color: #d4e8df; selection-color: #164f40;
            }
            QTabBar::tab { background: #e8e4db; border: 1px solid #cbc6bb; padding: 8px 16px; color: #4f5952; }
            QTabBar::tab:selected { background: #fbfaf6; color: #17664f; font-weight: 700; }
            QTabBar::tab:disabled { background: #e3e0d8; color: #68716c; }
            #inspectorPanel, #rawPanel { background: #f9f7f1; color: #27302b; }
            #inspectorPanel QLabel, #rawPanel QLabel { color: #303a34; font-weight: 600; }
            #validationPanel { background: #f9f7f1; color: #27302b; }
            #validationPanel QLabel { color: #303a34; font-weight: 600; }
            #validationPanel QListWidget { background: #fffefb; color: #303a34; border: 1px solid #cfc9bd; }
            #validationPanel QListWidget::item { color: #303a34; border-bottom: 1px solid #e4dfd5; }
            #inspectorPanel QLineEdit, #inspectorPanel QComboBox, #inspectorPanel QTextEdit, #inspectorPanel QSpinBox,
            #rawPanel QTextEdit { background: #fffefb; color: #202722; border: 1px solid #cfc9bd; }
            #targetIconPreview, #questIconPreview, #itemPreview { background: #eeeae1; color: #6c746e; border: 1px solid #cbc5b9; border-radius: 7px; font-size: 9px; }
            #pickerHint { color: #59645d; }
            #pickerDialog { background: #f3f1eb; color: #202722; }
            #pickerDialog #pickerSearch, #pickerDialog #pickerResults {
                background: #fffefb; color: #202722; border: 1px solid #cfc9bd;
                selection-background-color: #d4e8df; selection-color: #164f40;
            }
            #pickerDialog #pickerResults::item { color: #202722; }
            #pickerDialog #pickerResults::item:selected { background: #d4e8df; color: #164f40; }
            #pickerDialog #iconPickerResults { background: #fbfaf6; border: 1px solid #d7d2c7; border-radius: 8px; }
            #pickerDialog #iconPickerResults::item { color: #202722; padding: 5px; border-radius: 7px; }
            #pickerDialog #iconPickerResults::item:selected { background: #d4e8df; color: #164f40; }
            #autosaveState { color: #27705a; font-size: 11px; font-weight: 600; }
            #conditionSummary { color: #3d4942; background: #eef2ed; border: 1px solid #d5ddd7; border-radius: 7px; padding: 7px; }
            #fieldHelp { color: #526159; background: #edf3ef; border: 1px solid #d5e1da; border-radius: 6px; padding: 7px; }
            #statusPill { background: #dce9e3; color: #28634f; border-radius: 10px; padding: 5px 11px; }
            #chat { background: #fbfaf6; color: #27302b; border: none; }
            #chat a { color: #155f9a; }
            #actionList { background: #f0ede5; color: #33413a; border: 1px solid #ded9ce; }
            #actionList::item { color: #33413a; border-bottom: 1px solid #ded9ce; }
            #actionList::item:selected { background: #d4e8df; color: #164f40; }
            #prompt { background: transparent; color: #252c28; border: none; font-size: 14px; }
            #prompt { placeholder-text-color: #657169; }
            QPushButton:checked { background: #1f7059; color: white; border-color: #1f7059; }
            #agentButton { background: #d7f05c; color: #1c251f; border: none; font-weight: 800; padding: 9px 18px; }
            #agentButton:disabled { background: #d9d9ca; color: #68706b; border: 1px solid #c8c8ba; }
            QSplitter::handle { background: transparent; width: 7px; }
            #integratedWorkspace QSplitter::handle:hover { background: #d8ddd8; }
            #workspaceChapters { background: #fffefb; color: #303a34; border: 1px solid #d5d0c5; outline: none; }
            #workspaceChapters::item { color: #303a34; padding: 10px; border: none; }
            #workspaceChapters::item:selected { background: #d4e8df; color: #164f40; border: none; }
        """)

    def switch_view(self, index: int):
        self.view_title.setText("任务书编辑工作台")

    def show_validation(self):
        self.switch_view(1)
        self.editor_tabs.setCurrentWidget(self.expert_tabs)
        self.expert_tabs.setCurrentIndex(self.validation_tab_index)
        self.run_validation()

    def show_conditions_editor(self):
        self.editor_tabs.setCurrentWidget(self.task_tabs)
        self.task_tabs.setCurrentWidget(self.sections_editor)

    def show_command_menu(self) -> None:
        self.command_menu.popup(self.prompt.mapToGlobal(QPoint(0, self.prompt.height())))

    def select_agent_command(self, command: str) -> None:
        current = self.prompt.toPlainText().strip()
        if current.startswith("/"):
            _old, _space, remainder = current.partition(" ")
            text = f"{command} {remainder}".rstrip() + " "
        else:
            text = f"{command} {current}".rstrip() + " "
        self.prompt.setPlainText(text)
        self.prompt.moveCursor(QTextCursor.MoveOperation.End)
        self.prompt.setFocus()

    def _prompt_command_changed(self) -> None:
        text = self.prompt.toPlainText().strip()
        parsed = parse_request(text)
        label = INTENT_LABELS.get(parsed.intent, "未知指令" if parsed.explicit else "自动识别")
        selected = len(self.agent_context_chapter_ids) + len(self.agent_context_quest_ids)
        self.prompt_mode.setText(f"{label} · 已选 {selected}" if selected else label)
        if text == "/" and not self.command_menu.isVisible():
            QTimer.singleShot(0, self.show_command_menu)

    def _valid_agent_context(self) -> tuple[set[str], set[str]]:
        return self.editor_session.prune_agent_context(self.store)

    def update_agent_context_ui(self) -> None:
        chapter_ids, quest_ids = self._valid_agent_context()
        chapter_names = [
            chapter.title for chapter in self.store.project.chapters if chapter.id in chapter_ids
        ]
        quest_names = [
            quest.title
            for chapter in self.store.project.chapters
            for quest in chapter.quests
            if quest.id in quest_ids
        ]
        labels = [f"章节：{name}" for name in chapter_names] + [f"任务：{name}" for name in quest_names]
        if labels:
            visible = labels[:2]
            suffix = f" 等 {len(labels)} 项" if len(labels) > 2 else ""
            self.agent_context_label.setText("上下文：" + "；".join(visible) + suffix)
            self.clear_agent_context_button.show()
        else:
            self.agent_context_label.setText("上下文：未选择 · Alt + 点击任务或章节")
            self.clear_agent_context_button.hide()
        for item_index in range(self.chapter_list.count()):
            item = self.chapter_list.item(item_index)
            chapter_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
            chapter = self.store.chapter(chapter_id)
            if chapter is not None:
                marker = "AI · " if chapter_id in chapter_ids else ""
                item.setText(f"{marker}{chapter.title}\n{len(chapter.quests)} 个任务")
        for item in self.scene.items():
            if isinstance(item, QuestNode):
                item.set_agent_context(item.quest.id in quest_ids)
        if hasattr(self, "prompt_mode"):
            self._prompt_command_changed()

    def toggle_agent_chapter_context(self, chapter_id: str) -> None:
        if not self.editor_session.toggle_agent_chapter(self.store, chapter_id):
            return
        self.update_agent_context_ui()
        self.schedule_workspace_save()

    def toggle_agent_quest_context(self, quest_id: str) -> None:
        if not self.editor_session.toggle_agent_quest(self.store, quest_id):
            return
        self.update_agent_context_ui()
        self.schedule_workspace_save()

    def clear_agent_context(self) -> None:
        self.editor_session.clear_agent_context()
        self.update_agent_context_ui()
        self.schedule_workspace_save()

    def prepare_structured_agent_request(self, text: str):
        chapter_ids, quest_ids = self._valid_agent_context()
        previous_scope = (
            dict(self.agent.request_context)
            if self.agent and self.agent.request_context
            else dict(self._restored_agent_request_context)
        )
        prompt, scope, error = prepare_request(
            text,
            self.store,
            current_chapter_id=self.current_chapter_id,
            selected_chapter_ids=chapter_ids,
            selected_quest_ids=quest_ids,
            previous_scope=previous_scope,
        )
        if scope is not None:
            self._restored_agent_request_context = dict(scope)
        return prompt, scope, error

    def refresh_all(self):
        self.project_title.setText(self.store.project.title)
        self.editor_session.reconcile_selection(self.store)
        selected = self.current_chapter_id
        self.chapter_list.blockSignals(True)
        self.chapter_list.clear()
        for chapter in self.store.project.chapters:
            marker = "AI · " if chapter.id in self.agent_context_chapter_ids else ""
            item = QListWidgetItem(f"{marker}{chapter.title}\n{len(chapter.quests)} 个任务")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            item.setToolTip("Alt + 左键：加入或移出 Agent 上下文")
            self.chapter_list.addItem(item)
            if chapter.id == selected:
                self.chapter_list.setCurrentItem(item)
        self.chapter_list.blockSignals(False)
        self.refresh_canvas()
        self.run_validation()
        self.refresh_document_properties()
        if self.current_quest_id:
            found = self.store.quest(self.current_quest_id)
            if found is not None:
                self.load_inspector(found[1])
            else:
                self.current_quest_id = ""
                self.clear_inspector()
        self.schedule_workspace_save()
        self.update_agent_context_ui()

    def refresh_canvas(self):
        result = self.canvas_renderer.render(
            self.scene,
            self.store,
            self.current_chapter_id,
            selected_quest_id=self.current_quest_id,
            agent_quest_ids=self.agent_context_quest_ids,
            asset_index=self.asset_index,
            icon_loader=self.icon_pixmap_cache.get,
            agent_busy=self.agent_busy,
            on_quest_move=self._node_moved,
            on_image_move=self._chapter_image_moved,
            on_link_move=self._quest_link_moved,
            on_link_open=self.open_linked_quest,
        )
        bounds_chapter_id = self.current_chapter_id if result.chapter_title else ""
        same_chapter = bounds_chapter_id == self._canvas_bounds_chapter_id
        self.canvas.reset_scene_bounds(
            self.scene.itemsBoundingRect(), preserve=same_chapter,
        )
        self._canvas_bounds_chapter_id = bounds_chapter_id
        if not result.chapter_title:
            self.chapter_heading.setText("选择一个章节")
            self.schedule_workspace_save()
            return
        self.chapter_heading.setText(result.chapter_title)

    def _node_moved(self, quest_id: str, position):
        if self.agent_busy:
            return
        found = self.store.quest(quest_id)
        if found is None:
            return
        x = round(position.x() / 72, 2)
        y = round(position.y() / 72, 2)
        if found[1].x == x and found[1].y == y:
            return
        self.project_commands.move_quest(quest_id, x, y)
        self.append_action("move_quest", f"{quest_id} -> ({x}, {y})", refresh=False)

    def _chapter_object_moved(self, kind: str, object_id: str, position) -> None:
        x = round(position.x() / 72, 2)
        y = round(position.y() / 72, 2)
        self.project_commands.update_chapter_object(
            self.current_chapter_id, kind, object_id, {"x": x, "y": y},
        )
        self.append_action(f"move_{kind}", f"{object_id} -> ({x}, {y})", refresh=False)

    def _chapter_image_moved(self, object_id: str, position) -> None:
        self._chapter_object_moved("image", object_id, position)

    def _quest_link_moved(self, object_id: str, position) -> None:
        self._chapter_object_moved("link", object_id, position)

    def open_linked_quest(self, quest_id: str) -> None:
        found = self.store.quest(quest_id)
        if found is None:
            self.statusBar().showMessage(f"跳转目标不存在：{quest_id}", 4000)
            return
        chapter, quest = found
        self.current_chapter_id = chapter.id
        self.current_quest_id = quest.id
        self.refresh_all()
        self.load_inspector(quest)
        for item in self.scene.items():
            if isinstance(item, QuestNode) and item.quest.id == quest.id:
                item.setSelected(True)
                self.canvas.centerOn(item)
                break

    def fit_canvas(self):
        if self.scene.items():
            content = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
            self.canvas.fitInView(content, Qt.AspectRatioMode.KeepAspectRatio)
            self.canvas.ensure_scene_space()
            self.canvas.view_changed.emit()

    def select_chapter(self, current, _previous):
        if current and self.editor_session.select_chapter(
            self.store, current.data(Qt.ItemDataRole.UserRole),
        ):
            chapter = self.store.chapter(self.current_chapter_id)
            self.switch_view(1)
            self.refresh_canvas()
            self.fit_canvas()
            if self.current_quest_id:
                self.load_inspector(chapter.quests[0])
            else:
                self.clear_inspector()
            self.refresh_document_properties()
            self.schedule_workspace_save()

    def select_canvas_quest(self):
        selected_items = self.scene.selectedItems()
        selected = [item for item in selected_items if isinstance(item, QuestNode)]
        if not selected:
            chapter_object = next(
                (item for item in selected_items if isinstance(item, (ChapterImageNode, QuestLinkNode))),
                None,
            )
            if chapter_object is not None:
                image = isinstance(chapter_object, ChapterImageNode)
                pane = self.chapter_objects_editor.images if image else self.chapter_objects_editor.links
                self.editor_tabs.setCurrentWidget(self.chapter_tabs)
                self.chapter_tabs.setCurrentWidget(self.chapter_objects_editor)
                self.chapter_objects_editor.setCurrentWidget(pane)
                pane.refresh(chapter_object.object_id)
            return
        quest = selected[0].quest
        if self.connect_mode:
            self._handle_connection_click(quest)
            return
        self.editor_session.select_quest(self.store, quest.id)
        self.load_inspector(quest)
        self.schedule_workspace_save()

    def toggle_connect_mode(self, enabled: bool):
        self.connect_mode = enabled
        self.connection_controller.reset()
        self.scene.clearSelection()
        self.connection_hint.setText("先点击前置任务 A" if enabled else "空白处拖动画布 · 滚轮缩放")

    def _handle_connection_click(self, quest):
        result = self.connection_controller.click(quest.id)
        self.connection_hint.setText(result.message)
        if result.connected:
            self.append_action(
                "connect_quests", f"{result.source_id} -> {result.target_id}", refresh=False,
            )
            self._add_dependency_line(result.source_id, result.target_id)
        elif result.status == "error":
            self.statusBar().showMessage(f"连线已取消：{result.message}", 5000)

    def _add_dependency_line(self, source_id: str, target_id: str) -> None:
        """Render one new edge without rebuilding the scene during a mouse event."""
        nodes = {
            item.quest.id: item
            for item in self.scene.items()
            if isinstance(item, QuestNode)
        }
        source = nodes.get(source_id)
        target = nodes.get(target_id)
        if source is None or target is None:
            self.connection_hint.setText("连接已保存；切换章节后会显示连线")
            return
        if any(
            isinstance(item, (DependencyLine, CurvedDependencyLine))
            and item.source is source and item.target is target
            for item in self.scene.items()
        ):
            return
        self.scene.addItem(DependencyLine(source, target))

    def load_inspector(self, quest):
        self._loading_inspector = True
        try:
            data = inspector_data(self.store, quest)
            self.quest_title.setText(data.title)
            self.quest_subtitle.setText(data.subtitle)
            self.quest_icon.setText(data.icon)
            self.quest_chapter.clear()
            for chapter in self.store.project.chapters:
                self.quest_chapter.addItem(chapter.title, chapter.id)
            self.quest_chapter.setCurrentIndex(self.quest_chapter.findData(data.chapter_id))
            self._set_combo_value(self.quest_shape, data.shape)
            self._set_combo_value(self.quest_type, data.task_type)
            self.quest_target.setText(data.target)
            self.quest_count.setValue(data.count)
            self.quest_description.setPlainText(data.description)
            self.quest_tasks_raw.setPlainText(data.tasks_snbt)
            self.quest_rewards_raw.setPlainText(data.rewards_snbt)
            self.sections_editor.set_context(self.store, quest.id)
            self._update_condition_summary(quest)
            if data.raw_properties is not None:
                self.quest_properties.set_context(
                    data.raw_properties,
                    lambda changes, quest_id=quest.id: self.project_commands.update_quest_fields(
                        quest_id, changes,
                    ),
                )
            else:
                self.quest_properties.clear_context()
            self.autosave_state.setText("修改会实时同步到画布")
        finally:
            self._loading_inspector = False

    def clear_inspector(self):
        self._loading_inspector = True
        try:
            self.quest_title.clear()
            self.quest_subtitle.clear()
            self.quest_icon.clear()
            self.quest_chapter.clear()
            self.quest_shape.setCurrentIndex(-1)
            self.quest_type.setCurrentIndex(-1)
            self.quest_target.clear()
            self.quest_count.setValue(1)
            self.quest_description.clear()
            self.quest_tasks_raw.clear()
            self.quest_rewards_raw.clear()
            self.sections_editor.clear_context()
            self.condition_summary.setText("尚未设置完成条件")
            self.quest_properties.clear_context("请先选择任务节点")
            self.autosave_state.setText("请先选择一个任务")
        finally:
            self._loading_inspector = False

    def schedule_quest_autosave(self, *_args):
        if self._loading_inspector or not self.current_quest_id:
            return
        self.autosave_state.setText("正在同步修改…")
        self.inspector_autosave.start()

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str):
        index = combo.findData(value)
        if index < 0 and value:
            combo.addItem(f"自定义：{value}", value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def choose_target_item(self):
        if self.asset_index is None or not self.asset_index.items:
            QMessageBox.information(self, "选择目标 ID", "请先选择并扫描整合包，软件才能列出物品 ID 和图标。")
            return
        picker = ItemPickerDialog(self.asset_index, self.quest_target.text().strip(), self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.quest_target.setText(picker.selected_id)
            self.schedule_quest_autosave()

    def choose_quest_icon(self) -> None:
        if self.asset_index is None or not self.asset_index.items:
            QMessageBox.information(self, "选择任务图标", "请先选择并扫描整合包。")
            return
        picker = IconPickerDialog(
            self.asset_index,
            self.quest_icon.text().strip(),
            self,
            icon_loader=self.icon_pixmap_cache.get,
        )
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.quest_icon.setText(picker.selected_id)
            self.schedule_quest_autosave()

    def use_target_as_quest_icon(self) -> None:
        item_id = self.quest_target.text().strip()
        if not item_id:
            QMessageBox.information(self, "使用条件物品", "当前首个完成条件没有可用的目标物品 ID。")
            return
        if self.quest_type.currentData() != "item":
            QMessageBox.information(self, "使用条件物品", "当前首个完成条件不是物品条件，请改用“选择…”挑选图标。")
            return
        self.quest_icon.setText(item_id)
        self.schedule_quest_autosave()

    def clear_quest_icon(self) -> None:
        self.quest_icon.clear()
        self.schedule_quest_autosave()

    def pick_registry_value(self, registry: str, current: str = "") -> str:
        if registry == "item":
            if self.asset_index is None or not self.asset_index.items:
                QMessageBox.information(self, "选择物品", "请先选择并扫描整合包。")
                return ""
            picker = ItemPickerDialog(self.asset_index, current, self)
            return picker.selected_id if picker.exec() == QDialog.DialogCode.Accepted else ""
        values = {}
        if registry == "quest":
            values = {
                quest.id: f"{chapter.title} / {quest.title}"
                for chapter in self.store.project.chapters for quest in chapter.quests
            }
        elif registry == "reward_table" and hasattr(self.store, "list_reward_tables"):
            values = {
                str(table["data"].get("id")): str(table["data"].get("title") or table["path"])
                for table in self.store.list_reward_tables() if table["data"].get("id")
            }
        elif registry == "chapter_group" and hasattr(self.store, "document_objects"):
            values = {
                str(raw.get("id")): str(raw.get("title") or raw.get("id"))
                for raw in self.store.document_objects("chapter_groups.snbt", "chapter_groups") if raw.get("id")
            }
        elif self.asset_index and hasattr(self.asset_index, "registry_values"):
            values = self.asset_index.registry_values(registry)
        if not values:
            values = AssetIndex.builtin_registry_values(registry)
        if not values:
            QMessageBox.information(
                self, "选择注册项",
                "扫描结果中没有这类可靠 ID。可继续手动输入；实体、流体等运行时注册项将在游戏桥接阶段补全。",
            )
            return ""
        picker = RegistryPickerDialog(f"选择{REGISTRY_LABELS.get(registry, registry)} ID", values, current, self)
        return picker.selected_id if picker.exec() == QDialog.DialogCode.Accepted else ""

    def sections_changed(self):
        if not self.current_quest_id:
            return
        found = self.store.quest(self.current_quest_id)
        if found is None:
            return
        quest = found[1]
        self._loading_inspector = True
        try:
            task = quest.tasks[0] if quest.tasks else None
            self._set_combo_value(self.quest_type, task.type if task else "checkmark")
            self.quest_target.setText(task.target if task else "")
            self.quest_count.setValue(task.count if task else 1)
            self._update_condition_summary(quest)
            if hasattr(self.store, "raw_sections"):
                tasks, rewards = self.store.raw_sections(quest.id)
                self.quest_tasks_raw.setPlainText(to_snbt(tasks))
                self.quest_rewards_raw.setPlainText(to_snbt(rewards))
        finally:
            self._loading_inspector = False
        self.refresh_canvas()
        self.run_validation()

    def _update_condition_summary(self, quest) -> None:
        self.condition_summary.setText(condition_summary(quest))

    def refresh_document_properties(self):
        if not hasattr(self.store, "document"):
            self.chapter_properties.clear_context()
            self.book_properties.clear_context()
            self.chapter_groups_editor.set_store(None)
            self.reward_tables_editor.set_store(None)
            self.chapter_objects_editor.set_context(None, "")
            self.translations_editor.set_store(None)
            return
        chapter = self.store.chapter(self.current_chapter_id)
        if chapter is None:
            self.chapter_properties.clear_context("请先选择章节")
            self.chapter_objects_editor.set_context(None, "")
        else:
            self.chapter_properties.set_context(
                self.store.chapter_data(chapter.id),
                lambda changes, chapter_id=chapter.id: self.project_commands.update_chapter_fields(
                    chapter_id, changes,
                ),
            )
            self.chapter_objects_editor.set_context(self.store, chapter.id)
        self.book_properties.set_context(
            self.store.document("data.snbt"),
            lambda changes: self.project_commands.update_document("data.snbt", changes),
        )
        self.chapter_groups_editor.set_store(self.store)
        self.reward_tables_editor.set_store(self.store)
        self.translations_editor.set_store(self.store)

    def properties_changed(self):
        QTimer.singleShot(0, self.refresh_all)

    def update_target_preview(self):
        item_id = self.quest_target.text().strip()
        icon_path = self.asset_index.icon_for(item_id) if self.asset_index else ""
        pixmap = QPixmap(icon_path) if icon_path else QPixmap()
        if pixmap.isNull():
            self.target_icon_preview.setPixmap(QPixmap())
            self.target_icon_preview.setText("无图标")
            self.target_icon_preview.setToolTip(item_id or "尚未选择目标 ID")
            return
        self.target_icon_preview.setText("")
        self.target_icon_preview.setPixmap(
            pixmap.scaled(30, 30, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        asset = self.asset_index.items.get(item_id)
        status_reader = getattr(self.asset_index, "icon_status_text", None)
        status = status_reader(item_id) if callable(status_reader) else ""
        detail = f"{asset.name}\n{item_id}" if asset else item_id
        self.target_icon_preview.setToolTip(detail + (f"\n{status}" if status else ""))

    def update_quest_icon_preview(self, *_args) -> None:
        item_id = self.quest_icon.text().strip()
        effective_id = item_id or self.quest_target.text().strip()
        path = (
            self.asset_index.cached_icon_for(effective_id)
            if self.asset_index and effective_id else ""
        )
        pixmap = self.icon_pixmap_cache.get(path, 30) if path else QPixmap()
        if pixmap.isNull():
            self.quest_icon_preview.setPixmap(QPixmap())
            self.quest_icon_preview.setText("自动" if not item_id else "…")
        else:
            self.quest_icon_preview.setText("")
            self.quest_icon_preview.setPixmap(pixmap)
        source = "跟随完成条件" if not item_id else "自定义任务图标"
        self.quest_icon_preview.setToolTip(
            f"{source}\n{effective_id}" if effective_id else "未设置任务图标"
        )

    def save_project_title(self):
        self.store.project.title = self.project_title.text().strip() or "未命名任务书"
        self.schedule_workspace_save()

    def add_chapter(self):
        chapter = self.project_commands.create_chapter()
        self.current_chapter_id = chapter.id
        self.refresh_all()

    def move_current_chapter(self, delta: int) -> None:
        row = self.chapter_list.currentRow()
        if row < 0 or not self.current_chapter_id:
            return
        if self.project_commands.move_chapter(
            self.current_chapter_id, row, delta, self.chapter_list.count(),
        ):
            self.refresh_all()

    def remove_current_chapter(self) -> None:
        chapter = self.store.chapter(self.current_chapter_id)
        if chapter is None:
            return
        answer = QMessageBox.question(
            self, "删除章节", f"删除章节“{chapter.title}”及其中 {len(chapter.quests)} 个任务？\n此操作可通过撤销恢复。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.project_commands.remove_chapter(chapter.id):
            self.current_chapter_id = ""
            self.current_quest_id = ""
            self.refresh_all()

    def move_selected_quest_to_chapter(self, _index: int = -1) -> None:
        if self._loading_inspector or not self.current_quest_id:
            return
        target_id = str(self.quest_chapter.currentData() or "")
        found = self.store.quest(self.current_quest_id)
        if not target_id or found is None or found[0].id == target_id:
            return
        quest = self.project_commands.move_quest_to_chapter(
            self.current_quest_id, target_id,
        )
        self.current_chapter_id = target_id
        self.refresh_all()
        self.load_inspector(quest)

    def add_quest(self):
        if not self.current_chapter_id:
            self.add_chapter()
        center = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        quest = self.project_commands.add_quest(
            self.current_chapter_id,
            round(center.x() / 72, 2),
            round(center.y() / 72, 2),
        )
        self.current_quest_id = quest.id
        self.refresh_all()

    def copy_canvas_selection(self) -> None:
        selected = [
            item for item in self.scene.selectedItems()
            if isinstance(item, (QuestNode, ChapterImageNode, QuestLinkNode))
        ]
        if len(selected) != 1:
            self.statusBar().showMessage("复制时请选择一个任务、图片或跳转节点", 3500)
            return
        item = selected[0]
        if isinstance(item, QuestNode):
            self.canvas_clipboard = {"kind": "quest", "chapter_id": self.current_chapter_id, "id": item.quest.id}
        elif isinstance(item, ChapterImageNode):
            self.canvas_clipboard = {"kind": "image", "chapter_id": self.current_chapter_id, "id": item.object_id}
        else:
            self.canvas_clipboard = {"kind": "link", "chapter_id": self.current_chapter_id, "id": item.object_id}
        self.statusBar().showMessage("已复制画布对象，可在任意章节粘贴", 3500)

    def paste_canvas_selection(self, as_link: bool = False, with_dependencies: bool = True) -> None:
        if not self.canvas_clipboard or not self.current_chapter_id:
            self.statusBar().showMessage("画布剪贴板为空", 3000)
            return
        center = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        x, y = round(center.x() / 72, 2), round(center.y() / 72, 2)
        source = self.canvas_clipboard
        try:
            result = self.project_commands.paste_canvas_object(
                source,
                self.current_chapter_id,
                x,
                y,
                as_link=as_link,
                with_dependencies=with_dependencies,
            )
            selected_id, selected_kind = result.object_id, result.kind
            if selected_kind == "quest":
                self.current_quest_id = selected_id
            self.refresh_all()
            for item in self.scene.items():
                if selected_kind == "quest" and isinstance(item, QuestNode) and item.quest.id == selected_id:
                    item.setSelected(True)
                    break
                if selected_kind in {"image", "link"} and item.data(2) == selected_id:
                    item.setSelected(True)
                    break
            self.statusBar().showMessage("已粘贴到当前视野中心", 3000)
        except Exception as exc:
            self.statusBar().showMessage(f"无法粘贴：{exc}", 5000)

    def delete_canvas_selection(self) -> None:
        selected = [
            item for item in self.scene.selectedItems()
            if isinstance(item, (QuestNode, ChapterImageNode, QuestLinkNode))
        ]
        if not selected:
            return
        answer = QMessageBox.question(self, "删除画布对象", f"删除所选 {len(selected)} 个对象？此操作可撤销。")
        if answer != QMessageBox.StandardButton.Yes:
            return
        references = [
            ("quest", item.quest.id) if isinstance(item, QuestNode)
            else ("image", item.object_id) if isinstance(item, ChapterImageNode)
            else ("link", item.object_id)
            for item in selected
        ]
        self.project_commands.remove_canvas_objects(self.current_chapter_id, references)
        self.current_quest_id = ""
        self.refresh_all()

    def apply_quest_changes(self, raw_preferred: bool = False, quiet: bool = False):
        if not self.current_quest_id:
            if not quiet:
                QMessageBox.information(self, "任务属性", "请先在画布中选择一个任务。")
            return
        try:
            if raw_preferred:
                parsed_tasks, parsed_rewards = parse_sections(
                    self.quest_tasks_raw.toPlainText(), self.quest_rewards_raw.toPlainText(),
                )
            if raw_preferred and hasattr(self.store, "replace_quest_sections"):
                self.store.replace_quest_sections(self.current_quest_id, parsed_tasks, parsed_rewards)
            changes = dict(
                title=self.quest_title.text(),
                subtitle=self.quest_subtitle.text(),
                icon=self.quest_icon.text(),
                shape=self.quest_shape.currentData() or "",
                description=self.quest_description.toPlainText(),
            )
            self.project_commands.update_quest_basics(self.current_quest_id, changes)
            if raw_preferred:
                self.refresh_all()
            else:
                self.refresh_canvas()
                self.run_validation()
            self.autosave_state.setText("已实时同步")
            self.schedule_workspace_save()
        except Exception as exc:
            if quiet:
                self.autosave_state.setText(f"暂未同步：{exc}")
            else:
                QMessageBox.warning(self, "无法修改", str(exc))

    def remove_quest(self):
        if self.current_quest_id and self.project_commands.remove_quest(self.current_quest_id):
            self.current_quest_id = ""
            self.refresh_all()

    def undo(self):
        if self.store.undo():
            self.current_chapter_id = ""
            self.refresh_all()

    def redo(self):
        if self.store.redo():
            self.current_chapter_id = ""
            self.refresh_all()

    def _load_workspace_snapshot(self) -> None:
        try:
            loaded = self.workspace_repository.load()
            if loaded is None:
                return
            self.store = loaded.store
            state = WorkspaceState.from_dict(loaded.session, self.store)
            self.project_path = state.project_path
            self.last_modpack_folder = state.last_modpack_folder
            self.current_chapter_id = state.current_chapter_id
            self.current_quest_id = state.current_quest_id
            self.chat_records = state.chat
            self.action_records = state.actions
            self._restored_agent_history = state.agent_history
            self._restored_agent_run_state = state.agent_run_state
            self._restored_agent_request_context = state.agent_request_context
            self.agent_prompt_queue = state.agent_queue
            self._restored_view = state.view
            self._restored_prompt = state.prompt
            self.agent_context_chapter_ids = state.agent_chapter_ids
            self.agent_context_quest_ids = state.agent_quest_ids
            self._workspace_restored = True
        except Exception:
            LOGGER.exception("Failed to restore workspace snapshot")

    def _restore_workspace_ui(self) -> None:
        if not self._workspace_restored:
            return
        self.chat.clear()
        for value in self.chat_records:
            self._render_chat(value["role"], value["text"])
        saved_actions = list(self.action_records)
        self.action_list.clear()
        for value in saved_actions:
            self._render_action(value["name"], value["detail"])
        # Restored actions are history, not live Agent events.  The progress bar
        # must describe only a request that is running in this process.
        self.agent_panel.set_progress_idle()
        restored_phase = str(self._restored_agent_run_state.get("phase", ""))
        if restored_phase in {"needs_attention", "interrupted", "failed"}:
            self._agent_attention_message = "当前：上一轮尚未完成，可发送“继续”恢复执行"
            self.agent_current_label.setText(self._agent_attention_message)
        self.prompt.setPlainText(getattr(self, "_restored_prompt", ""))
        QTimer.singleShot(0, self._restore_workspace_view)

    def _restore_workspace_view(self) -> None:
        zoom = float(self._restored_view.get("zoom", 1.0) or 1.0)
        current = self.canvas.transform().m11() or 1.0
        zoom = max(0.15, min(zoom, 4.0))
        self.canvas.scale(zoom / current, zoom / current)
        if "center_x" in self._restored_view and "center_y" in self._restored_view:
            self.canvas.centerOn(
                float(self._restored_view.get("center_x", 0.0) or 0.0),
                float(self._restored_view.get("center_y", 0.0) or 0.0),
            )
        else:
            self.canvas.horizontalScrollBar().setValue(int(self._restored_view.get("scroll_x", 0) or 0))
            self.canvas.verticalScrollBar().setValue(int(self._restored_view.get("scroll_y", 0) or 0))
        self.canvas.ensure_scene_space()

    def schedule_workspace_save(self) -> None:
        if self._workspace_enabled and self._workspace_ready and hasattr(self, "workspace_autosave"):
            self.workspace_autosave.start()

    def _save_workspace_snapshot(self) -> None:
        if not self._workspace_enabled or not self._workspace_ready:
            return
        if self.agent_busy or self.agent_thread is not None:
            self.workspace_autosave.start(1200)
            return
        try:
            history = list(self.agent.history) if self.agent else list(self._restored_agent_history)
            view_center = self.canvas.mapToScene(self.canvas.viewport().rect().center())
            session = WorkspaceState(
                project_path=self.project_path,
                last_modpack_folder=self.last_modpack_folder or self.store.project.mod_folder,
                current_chapter_id=self.current_chapter_id,
                current_quest_id=self.current_quest_id,
                chat=self.chat_records,
                actions=self.action_records,
                agent_history=history,
                agent_run_state=(
                    self.agent.export_run_state() if self.agent else self._restored_agent_run_state
                ),
                agent_request_context=(
                    dict(self.agent.request_context)
                    if self.agent else self._restored_agent_request_context
                ),
                agent_queue=self.agent_prompt_queue,
                agent_chapter_ids=set(self.agent_context_chapter_ids),
                agent_quest_ids=set(self.agent_context_quest_ids),
                prompt=self.prompt.toPlainText(),
                view={
                    "zoom": self.canvas.transform().m11(),
                    "center_x": view_center.x(),
                    "center_y": view_center.y(),
                    "scroll_x": self.canvas.horizontalScrollBar().value(),
                    "scroll_y": self.canvas.verticalScrollBar().value(),
                },
            ).to_dict()
            self.workspace_repository.save(self.store, session)
        except Exception:
            LOGGER.exception("Failed to save workspace snapshot")

    def _reset_workspace_conversation(self) -> None:
        self.chat_records.clear()
        self.action_records.clear()
        self._restored_agent_history.clear()
        self._restored_agent_run_state.clear()
        self._restored_agent_request_context.clear()
        self.agent_prompt_queue.clear()
        self.chat.clear()
        self.action_list.clear()
        self.agent_panel.reset_progress()
        self.append_chat(
            "agent",
            "我是项目 Agent。先扫描整合包，然后告诉我想制作什么；执行进度与安全检查点会显示在下面。",
        )

    def closeEvent(self, event) -> None:
        if self._workspace_enabled and not self.agent_busy and self.agent_thread is None:
            self._save_workspace_snapshot()
        for thread in (self.scan_thread, self.icon_prewarm_thread, self.cache_cleanup_thread):
            if thread is not None and thread.isRunning():
                thread.requestInterruption()
                thread.wait(2000)
        super().closeEvent(event)

    def attach_game_bridge(self, bridge: StudioBridgeServer | None) -> None:
        self.bridge_server = bridge
        if bridge is None:
            self.game_bridge_label.setText("游戏连接：本地桥启动失败，桌面编辑仍可使用")
            return
        self.game_bridge_label.setText(f"游戏连接：桥已就绪 · 本机端口 {bridge.port}")
        self.bridge_status_timer = QTimer(self)
        self.bridge_status_timer.setInterval(1000)
        self.bridge_status_timer.timeout.connect(self._refresh_game_bridge_status)
        self.bridge_status_timer.start()

    def _refresh_game_bridge_status(self) -> None:
        bridge = getattr(self, "bridge_server", None)
        if bridge is None:
            return
        value = bridge.service.snapshot()
        connected = (value.get("available") and value.get("project_id")
                     and int(value.get("seconds_since_sync", 999)) < 30)
        if connected and not self.agent_busy and self.agent_thread is None:
            self._enter_game_backend_mode()
        if self._game_backend_mode:
            self.open_game_book_button.setEnabled(False)
            self.sync_game_book_button.setEnabled(False)
            if connected:
                self.backend_status.setText(
                    f"已连接 {value.get('loader', '')} {value.get('minecraft_version', '')} · "
                    f"Mod {value.get('mod_version', '')}\n"
                    f"选区：{value.get('selected_chapters', 0)} 章 / {value.get('selected_quests', 0)} 任务 · "
                    + ("服务器允许编辑" if value.get('server_can_edit') else "服务器未授予编辑权限"))
                self._refresh_backend_history(bridge.service, value)
            else:
                self.backend_status.setText("游戏连接已中断，等待重新连接。请在游戏中打开任务书。")
            self._process_game_agent_requests()
            return
        if not value.get("available"):
            self.open_game_book_button.setEnabled(False)
            self.sync_game_book_button.setEnabled(False)
            self._process_game_agent_requests()
            return
        loader = str(value.get("loader", "")).capitalize()
        selected = int(value.get("selected_quests", 0) or 0)
        chapter = str(value.get("chapter_title", "") or "未从选中任务确定章节")
        age = int(value.get("seconds_since_sync", 0) or 0)
        permission = ("可编辑 · 自动应用 · 可撤回"
                      if value.get("server_can_edit") is True
                      else "服务器未授予编辑权限")
        self.game_bridge_label.setText(
            f"游戏连接：{loader} {value.get('minecraft_version', '')} · "
            f"FTBQ {value.get('ftb_quests_version', '')} · Mod {value.get('mod_version', '')}\n"
            f"权限：{permission}\n"
            f"最近同步：{chapter} · 选中 {selected} 个任务 · {age} 秒前"
        )
        has_snapshot = bridge.service.has_latest_book_snapshot()
        self.open_game_book_button.setEnabled(has_snapshot and not self.agent_busy)
        self.sync_game_book_button.setEnabled(
            has_snapshot and self._live_game_base_payload is not None
            and self._live_game_pending_payload is None and not self.agent_busy
        )
        self._sync_game_timeline()
        self._process_game_agent_requests()

    def _sync_game_timeline(self) -> None:
        bridge = getattr(self, "bridge_server", None)
        if bridge is None:
            return
        snapshot = bridge.service.snapshot()
        session_id = str(snapshot.get("session_id", ""))
        if not session_id:
            session_id = getattr(bridge.service, "_latest_session_id", "")
        if not session_id:
            return
        try:
            events = bridge.service.events(session_id, self._game_event_cursor, 200)
        except Exception:
            LOGGER.exception("Unable to synchronize game project timeline")
            return
        for event in events:
            self._game_event_cursor = max(self._game_event_cursor, int(event["event_id"]))
            kind = str(event.get("kind", ""))
            payload = event.get("payload", {})
            self._applying_shared_events = True
            try:
                if kind == "chat.user" and event.get("origin") == "game":
                    self.append_chat("user", "[游戏内] " + str(payload.get("text", "")))
                elif (kind == "chat.assistant" and event.get("origin") == "studio"
                      and payload.get("surface") != "studio"):
                    # Game Agent answers are already rendered by its game-origin user event.
                    self.append_chat("agent", "[游戏会话] " + str(payload.get("text", "")))
                elif kind.startswith("work.") or kind.startswith("change."):
                    self.append_action(kind, json.dumps(payload, ensure_ascii=False), refresh=False)
            finally:
                self._applying_shared_events = False
            if kind == "change.applied" and self._live_game_pending_payload is not None:
                self._live_game_base_payload = deepcopy(self._live_game_pending_payload)
                self._live_game_pending_payload = None
                self._live_game_revision = str(payload.get("server_book_revision", ""))
                self.statusBar().showMessage("工作台修改已由游戏服务器应用，可在游戏内撤回", 7000)
            elif kind in {"change.failed", "change.conflict", "change.undone"}:
                self._live_game_pending_payload = None
                if kind == "change.undone":
                    self._live_game_base_payload = None
                    self.statusBar().showMessage("游戏端已撤回修改，请重新载入实时任务书", 7000)

    def open_live_game_book(self) -> None:
        if self._game_backend_mode:
            return
        bridge = getattr(self, "bridge_server", None)
        payload = bridge.service.latest_book_payload() if bridge is not None else None
        if payload is None:
            QMessageBox.information(self, "游戏任务书", "游戏端尚未上传完整任务书快照。")
            return
        try:
            self.store = FTBQuestStore._from_project_payload(payload)
            self.store.project.title = "游戏任务书 · " + self.store.project.title
            self._live_game_base_payload = deepcopy(payload)
            self._live_game_revision = str(payload.get("live_sync", {}).get("book_revision", ""))
            self._live_game_pending_payload = None
            self.project_path = ""
            self.current_chapter_id = ""
            self.current_quest_id = ""
            self.agent = None
            self.agent_context_chapter_ids.clear()
            self.agent_context_quest_ids.clear()
            self.refresh_all()
            self.statusBar().showMessage("已切换到实时游戏任务书；编辑后点击“同步到游戏”", 7000)
        except Exception as exc:
            QMessageBox.critical(self, "载入游戏任务书失败", str(exc))

    def sync_live_game_book(self) -> None:
        if self._game_backend_mode:
            return
        bridge = getattr(self, "bridge_server", None)
        if bridge is None or self._live_game_base_payload is None:
            return
        try:
            desired = self.store._project_payload()
            result = bridge.service.queue_studio_book({
                "base_book_revision": self._live_game_revision,
                "project": desired,
                "summary": "Studio 工作台任务书修改",
            })
            if result.get("status") == "unchanged":
                self.statusBar().showMessage("工作台任务书没有需要同步的修改", 5000)
                return
            self._live_game_pending_payload = deepcopy(desired)
            self.sync_game_book_button.setEnabled(False)
            self.statusBar().showMessage(
                f"已发送 {result.get('operation_count', 0)} 项修改，等待游戏服务器应用", 7000,
            )
        except Exception as exc:
            QMessageBox.critical(self, "同步到游戏失败", str(exc))

    def _process_game_agent_requests(self) -> None:
        bridge = getattr(self, "bridge_server", None)
        if bridge is None:
            return
        running = self.game_agent_task
        if running is not None:
            if running.is_alive():
                return
            self.game_agent_task = None
        if self.agent_busy:
            return
        record = bridge.service.requests.take_next()
        if record is None:
            return
        context = bridge.service.agent_context(record.session_id)
        if context is None:
            bridge.service.requests.fail(record.id, "游戏上下文已经失效，请重新同步后再试")
            return
        if not self.refresh_ai_state():
            bridge.service.requests.fail(record.id, "Studio 尚未配置可用的 AI 模型")
            return
        try:
            client = self._load_client()
        except Exception as exc:
            bridge.service.requests.fail(record.id, str(exc) or type(exc).__name__)
            return
        task = LiveProjectAgentTask(bridge.service, record, context, client,
                                    asset_index=self.asset_index)
        self.game_agent_task = task
        task.start()

    def new_project(self):
        if self._game_backend_mode:
            return
        if QMessageBox.question(self, "新建项目", "创建新项目？未保存的修改将丢失。") == QMessageBox.StandardButton.Yes:
            self.store = self._starter_store()
            self.project_path = ""
            self.current_chapter_id = ""
            self.agent = None
            self.agent_context_chapter_ids.clear()
            self.agent_context_quest_ids.clear()
            self._reset_workspace_conversation()
            self.refresh_all()

    def open_project(self):
        if self._game_backend_mode:
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开 AutoFTBQ Studio 项目", "", PROJECT_FILTER)
        if not path:
            return
        try:
            self.store = self.project_files.load(path)
            self.project_path = path
            self.current_chapter_id = ""
            self.agent = None
            self.agent_context_chapter_ids.clear()
            self.agent_context_quest_ids.clear()
            self._reset_workspace_conversation()
            self.refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))

    def save_project(self):
        if self._game_backend_mode:
            return
        self.save_project_title()
        if getattr(self.store, "is_real", False):
            try:
                result = self.project_files.save(self.store)
                message = f"已写回 {result['saved']} 个真实章节"
                if result.get("backup"):
                    message += f"，备份：{result['backup']}"
                self.statusBar().showMessage(message, 8000)
                self.schedule_workspace_save()
            except Exception as exc:
                QMessageBox.critical(self, "保存失败", str(exc))
            return
        path = self.project_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "保存 AutoFTBQ Studio 项目", "questbook.autoftbq.json", PROJECT_FILTER)
        if not path:
            return
        try:
            self.project_files.save(self.store, path)
            self.project_path = path
            self.statusBar().showMessage(f"已保存：{path}", 5000)
            self.schedule_workspace_save()
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))

    def scan_modpack(self):
        if self.scan_thread is not None:
            self.scan_thread.requestInterruption()
            self.scan_button.setEnabled(False)
            self.scan_button.setText("正在停止资源恢复…")
            self.statusBar().showMessage("正在停止资源恢复，请稍候", 3000)
            return
        selected_folder = QFileDialog.getExistingDirectory(
            self, "选择整合包根目录或 mods 文件夹", self.store.project.mod_folder
        )
        if not selected_folder:
            return
        folder = os.path.abspath(selected_folder)
        if os.path.basename(folder).casefold() == "mods":
            folder = os.path.dirname(folder)
        self._start_modpack_scan(folder)

    def _restore_last_modpack(self) -> None:
        folder = str(self.last_modpack_folder or self.store.project.mod_folder or "").strip()
        if not folder:
            return
        folder = os.path.abspath(folder)
        if os.path.basename(folder).casefold() == "mods":
            folder = os.path.dirname(folder)
        if not os.path.isdir(folder):
            self.modpack_status.setText(
                f"上次整合包路径已失效\n{folder}\n请重新选择整合包"
            )
            self.scan_button.setText("重新选择并扫描整合包")
            return
        self._start_modpack_scan(folder, automatic=True, preserve_store=True)

    def _start_modpack_scan(
        self, folder: str, *, automatic: bool = False, preserve_store: bool = False,
    ) -> bool:
        if self.scan_thread is not None:
            if not automatic:
                self.statusBar().showMessage("整合包仍在后台扫描中", 3000)
            return False
        folder = os.path.abspath(folder)
        if not os.path.isdir(folder):
            if automatic:
                self.modpack_status.setText(f"上次整合包路径已失效\n{folder}\n请重新选择整合包")
            else:
                QMessageBox.warning(self, "无法扫描", f"整合包目录不存在：\n{folder}")
            return False
        self._automatic_scan = automatic
        self._scan_preserve_store = preserve_store
        self.last_modpack_folder = folder
        self.store.project.mod_folder = folder
        self.scan_button.setEnabled(True)
        self.scan_button.setText("停止自动恢复" if automatic else "停止后台扫描")
        self.modpack_status.setText(
            ("正在自动恢复上次整合包资源…" if automatic else "正在准备后台扫描…")
            + "\n界面可以继续操作"
        )
        thread = ModpackScanWorker(
            folder,
            os.path.join(ROOT_DIR, ".autoftbq_cache", "icons"),
            self,
            load_quest_book=not preserve_store,
        )
        thread.progress.connect(self._scan_progress)
        thread.completed.connect(self._scan_completed)
        thread.failed.connect(self._scan_failed)
        thread.cancelled.connect(self._scan_cancelled)
        thread.finished.connect(self._scan_finished)
        self.scan_thread = thread
        thread.start()
        self.schedule_workspace_save()
        return True

    def _scan_progress(self, message: str):
        now = time.monotonic()
        if str(message).startswith("扫描模组 ") and now - self._scan_last_progress_at < 0.1:
            return
        self._scan_last_progress_at = now
        self.modpack_status.setText(f"{message}\n界面可以继续操作")

    def _scan_completed(self, result: dict):
        folder = result["folder"]
        items = result["items"]
        self.asset_index = result["asset_index"]
        availability_reader = getattr(self.asset_index, "agent_availability_map", None)
        self.toolbox = QuestToolbox(
            items, result["recipes"],
            availability=availability_reader() if callable(availability_reader) else {},
        )
        self.icon_pixmap_cache.clear()
        self.refresh_shape_choices()
        self.update_target_preview()
        store = result["store"]
        loaded_text = ""
        if store is not None and not self._scan_preserve_store:
            self.store = store
            self.store.project.mod_folder = folder
            self.last_modpack_folder = folder
            self.project_path = result["quest_root"]
            self.current_chapter_id = ""
            self.current_quest_id = ""
            loaded_text = f"\n已打开真实任务书：{len(store.project.chapters)} 个章节"
            load_errors = list(getattr(store, "load_errors", []))
            if load_errors:
                loaded_text += f"，{len(load_errors)} 个文件读取失败"
        else:
            self.store.project.mod_folder = folder
            if self._automatic_scan:
                loaded_text = "\n已自动恢复上次整合包资源，未覆盖当前草稿"
        total = sum(len(value) for value in items.values())
        assets = self.asset_index.summary()
        agent_allowed = int(assets.get("agent_allowed", total))
        isolated = int(assets.get("agent_blocked", 0)) + int(assets.get("agent_uncertain", 0))
        self.modpack_status.setText(
            f"已读取 {len(items)} 个命名空间 / {total} 个物品\n"
            f"Agent 安全物品 {agent_allowed} 个，隔离可疑物品 {isolated} 个\n"
            f"已建立 {assets['resources']} 项资源目录，任务图标正在后台准备"
            f"{loaded_text}"
        )
        self.agent = None
        self.append_action("scan_modpack", f"{total} items")
        self.refresh_all()
        self._start_icon_prewarm()
        self._start_cache_cleanup()
        if not self._scan_preserve_store:
            self.fit_canvas()
        self.schedule_workspace_save()

    def _quest_icon_ids(self) -> list[str]:
        chapters = list(self.store.project.chapters)
        if self.current_chapter_id:
            chapters.sort(key=lambda chapter: chapter.id != self.current_chapter_id)
        result = []
        for chapter in chapters:
            for quest in chapter.quests:
                task = quest.tasks[0] if quest.tasks else None
                icon_id = quest.icon or (task.target if task else "")
                if icon_id and icon_id not in result:
                    result.append(icon_id)
        return result

    def _chapter_image_ids(self) -> list[str]:
        result = []
        if not hasattr(self.store, "chapter_data"):
            return result
        for chapter in self.store.project.chapters:
            raw = self.store.chapter_data(chapter.id)
            images = raw.get("images", []) if isinstance(raw, dict) else []
            for value in images if isinstance(images, list) else []:
                image_id = str(value.get("image") or "") if isinstance(value, dict) else ""
                if image_id and image_id not in result:
                    result.append(image_id)
        return result

    def _start_icon_prewarm(self) -> None:
        if self.asset_index is None:
            return
        previous = self.icon_prewarm_thread
        if previous is not None and previous.isRunning():
            previous.requestInterruption()
        worker = IconPrewarmWorker(
            self.asset_index, self._quest_icon_ids(), self._chapter_image_ids(), self,
        )
        worker.icon_ready.connect(
            lambda item_id, path, source=worker: self._icon_prewarm_ready(source, item_id, path)
        )
        worker.completed.connect(
            lambda count, source=worker: self._icon_prewarm_completed(source, count)
        )
        worker.finished.connect(lambda source=worker: self._icon_prewarm_finished(source))
        self.icon_prewarm_thread = worker
        worker.start()

    def _icon_prewarm_ready(self, source, item_id: str, path: str) -> None:
        if source is not self.icon_prewarm_thread:
            return
        for item in self.scene.items():
            if isinstance(item, QuestNode) and item.icon_id == item_id:
                item.set_icon_path(path)

    def _icon_prewarm_completed(self, source, count: int) -> None:
        if source is not self.icon_prewarm_thread:
            return
        self.refresh_canvas()
        if count:
            self.statusBar().showMessage(f"已在后台准备 {count} 个任务图标", 3000)

    def _icon_prewarm_finished(self, source) -> None:
        if source is self.icon_prewarm_thread:
            self.icon_prewarm_thread = None
        source.deleteLater()

    def _start_cache_cleanup(self) -> None:
        if (self.asset_index is None or self.cache_cleanup_thread is not None
                or not callable(getattr(self.asset_index, "cleanup_cache", None))):
            return
        worker = CacheCleanupWorker(self.asset_index, self)
        worker.completed.connect(
            lambda result, source=worker: self._cache_cleanup_completed(source, result)
        )
        worker.finished.connect(lambda source=worker: self._cache_cleanup_finished(source))
        self.cache_cleanup_thread = worker
        worker.start()

    def _cache_cleanup_completed(self, source, result: dict) -> None:
        if source is not self.cache_cleanup_thread:
            return
        removed = int((result or {}).get("removed", 0))
        if removed:
            logging.getLogger(LOGGER_NAME).info("Removed %s stale icon cache files", removed)

    def _cache_cleanup_finished(self, source) -> None:
        if source is self.cache_cleanup_thread:
            self.cache_cleanup_thread = None
        source.deleteLater()

    def refresh_shape_choices(self) -> None:
        current = str(self.quest_shape.currentData() or "")
        labels = {value: label for label, value in QUEST_SHAPES}
        values = [value for _label, value in QUEST_SHAPES]
        if self.asset_index and hasattr(self.asset_index, "quest_shapes"):
            values.extend(value for value in self.asset_index.quest_shapes() if value not in values)
        self.quest_shape.blockSignals(True)
        self.quest_shape.clear()
        for value in values:
            self.quest_shape.addItem(labels.get(value, f"主题：{value}"), value)
        self._set_combo_value(self.quest_shape, current)
        self.quest_shape.blockSignals(False)

    def _scan_failed(self, message: str):
        self.modpack_status.setText(f"扫描失败：{message}")
        if not self._automatic_scan:
            QMessageBox.critical(self, "扫描失败", message)

    def _scan_cancelled(self):
        self.modpack_status.setText("资源恢复已停止\n可以随时重新扫描整合包")
        self.statusBar().showMessage("资源恢复已停止", 3000)

    def _scan_finished(self):
        thread = self.scan_thread
        self.scan_thread = None
        self.scan_button.setEnabled(True)
        self.scan_button.setText("重新扫描整合包")
        self._automatic_scan = False
        self._scan_preserve_store = False
        if thread is not None:
            thread.deleteLater()

    def run_validation(self):
        issues = list(self.store.validate(self.toolbox.all_items))
        if self.asset_index is not None:
            issues.extend(AgentItemPolicy(self.store, self.asset_index).existing_warnings())
        self.validation_list.clear()
        if not issues:
            self.validation_list.addItem("通过：没有发现结构问题")
            return issues
        for issue in issues:
            prefix = "错误" if issue["severity"] == "error" else "提醒"
            self.validation_list.addItem(f"{prefix}  {issue['location']}  ·  {issue['message']}")
        return issues

    def export_snbt(self):
        if self._game_backend_mode:
            return
        issues = self.run_validation()
        errors = [issue for issue in issues if issue["severity"] == "error"]
        if errors:
            QMessageBox.warning(self, "暂不能导出", "请先处理检查结果中的错误。")
            return
        folder = QFileDialog.getExistingDirectory(self, "选择 FTB Quests 输出目录")
        if not folder:
            return
        try:
            result = self.project_files.export(self.store, folder)
            if result["kind"] == "directory":
                message = f"已写入 {result['saved']} 个任务书文件：\n{result['root']}"
                if result.get("backup"):
                    message += f"\n原文件备份：{result['backup']}"
            else:
                message = f"任务书已写入：\n{result['output']}"
            QMessageBox.information(self, "导出完成", message)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _load_client(self):
        config = load_config(self.ai_config_path)
        client = client_from_config(config)
        provider = config.get("provider") or config.get("engine", "AI")
        self.model_label.setText(f"已连接 {provider} / {getattr(client, 'model', 'default')} · 白名单工具模式")
        return client

    def refresh_ai_state(self) -> bool:
        config = load_config(self.ai_config_path)
        error = validate_ai_config(config)
        self.ai_configured = not error
        self.prompt.setEnabled(self.ai_configured)
        self.send_button.setEnabled(self.ai_configured)
        self.send_button.setText(
            f"加入队列 · {len(self.agent_prompt_queue)}" if self.agent_thread is not None else "交给 Agent"
        )
        if self.ai_configured:
            provider = config.get("provider") or config.get("engine", "AI")
            model = config.get("ollama_model") if config.get("engine") == "ollama" else config.get("api_model")
            self.model_label.setText(f"已配置 {provider} / {model or '默认模型'} · 等待 Agent 调用")
            self.agent_state.setText("待命")
        else:
            self.model_label.setText(f"尚未配置 AI：{error}。离线编辑功能仍可使用。")
            self.agent_state.setText("未配置")
        return self.ai_configured

    def open_ai_setup(self, required: bool = False) -> bool:
        dialog = AISetupDialog(self.ai_config_path, required=required, parent=self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            self.agent = None
        self.refresh_ai_state()
        return accepted

    def toggle_action_details(self, visible: bool) -> None:
        self.agent_panel.toggle_action_details(visible)

    def _progress_item(self, text: str, tooltip: str = "") -> None:
        self.agent_panel._progress_item(text, tooltip)

    def update_agent_progress(self, name: str, detail: str) -> None:
        self.agent_panel.update_progress(name, detail)

    def undo_agent_checkpoint(self) -> None:
        if self.agent_busy or not self.agent:
            return
        if not self.agent.rollback_last_checkpoint():
            self.statusBar().showMessage("目前没有可以撤销的 Agent 检查点", 4000)
            return
        self.append_action("agent_checkpoint_rollback", "用户撤销最近一个安全步骤", refresh=False)
        self.refresh_all()
        self.undo_checkpoint_button.setEnabled(self.agent.checkpoint_count > 0)
        self.statusBar().showMessage("已撤销最近一个 Agent 检查点，之前的成果仍然保留", 5000)

    def ensure_ai_setup(self) -> None:
        if not self.refresh_ai_state():
            self.open_ai_setup(required=True)

    def send_to_agent(self):
        if self._game_backend_mode:
            return
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            return
        if self.agent_thread is not None:
            queue_size = self.agent_runtime.enqueue(prompt)
            self.prompt.clear()
            self.append_action("agent_queue", prompt, refresh=False)
            self.send_button.setText(f"加入队列 · {queue_size}")
            self.agent_state.setText(f"工作中 · 已排队 {queue_size} 条")
            self.statusBar().showMessage("要求已加入 Agent 队列，将在本轮完成后自动发送", 5000)
            return
        if not self.ai_configured and not self.open_ai_setup(required=True):
            return
        structured, scope, clarification = self.prepare_structured_agent_request(prompt)
        if clarification:
            self.append_chat("agent", clarification)
            self.statusBar().showMessage(clarification, 6000)
            return
        try:
            prepared = self.agent_session.prepare(
                current_agent=self.agent,
                store=self.store,
                client_factory=self._load_client,
                toolbox=self.toolbox,
                asset_index=self.asset_index,
                structured_prompt=structured,
                request_context=scope,
                restored_history=self._restored_agent_history,
                restored_run_state=self._restored_agent_run_state,
            )
            self.agent = prepared.agent
        except Exception as exc:
            LOGGER.exception("Failed to initialize Agent client")
            QMessageBox.warning(self, "Agent 未连接", str(exc))
            return
        self.append_chat("user", prompt)
        self.prompt.clear()
        self._save_workspace_snapshot()
        self.agent_thread = prepared.worker
        self.agent_thread.action.connect(self.append_action)
        self.agent_thread.answered.connect(self.agent_answered)
        self.agent_thread.failed.connect(self.agent_failed)
        self.agent_thread.finished.connect(self.agent_finished)
        self.set_agent_busy(True)
        self.agent_thread.start()

    def set_agent_busy(self, busy: bool) -> None:
        """Keep navigation responsive while preventing concurrent project writes."""
        if self.agent_busy == bool(busy):
            return
        self.agent_busy = bool(busy)
        if busy and self.connect_button.isChecked():
            self.connect_button.setChecked(False)
        if busy:
            self._agent_attention_message = ""
            self._agent_control_states = {
                control: control.isEnabled() for control in self.agent_write_controls
            }
            self._agent_shortcut_states = {
                shortcut: shortcut.isEnabled() for shortcut in self.agent_write_shortcuts
            }
            for control in self.agent_write_controls:
                control.setEnabled(False)
            for shortcut in self.agent_write_shortcuts:
                shortcut.setEnabled(False)
            self.agent_progress_bar.setRange(0, 0)
            self.agent_progress_bar.setFormat("Agent 工作中")
            self.agent_current_label.setText("当前：连接模型并准备下一步")
        else:
            for control in self.agent_write_controls:
                control.setEnabled(self._agent_control_states.get(control, True))
            for shortcut in self.agent_write_shortcuts:
                shortcut.setEnabled(self._agent_shortcut_states.get(shortcut, True))
            self._agent_control_states.clear()
            self._agent_shortcut_states.clear()
        self.editor_tabs.setEnabled(not busy)
        for item in self.scene.items():
            if isinstance(item, (QuestNode, ChapterImageNode, QuestLinkNode)):
                item.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, not busy)
        self.prompt.setEnabled(self.ai_configured)
        self.send_button.setEnabled(self.ai_configured)
        self.send_button.setText(
            f"加入队列 · {len(self.agent_prompt_queue)}" if busy else "交给 Agent"
        )
        self.ai_setup_button.setEnabled(not busy)
        self.undo_checkpoint_button.setEnabled(
            not busy and bool(self.agent and self.agent.checkpoint_count > 0)
        )
        self.agent_state.setText("工作中 · 可浏览" if busy else ("待命" if self.ai_configured else "未配置"))
        self.connection_hint.setText(
            "Agent 正在修改 · 可切换章节和查看，编辑暂时锁定"
            if busy else "空白处拖动画布 · 滚轮缩放"
        )

    def agent_answered(self, text):
        self.append_chat("agent", text)
        self.refresh_all()
        review = AgentReview.from_agent(self.agent)
        if review.pending:
            dialog = QMessageBox(self)
            dialog.setWindowTitle("确认 Agent 修改")
            dialog.setIcon(QMessageBox.Icon.Question)
            dialog.setText(
                f"{review.heading}\n\n{review.acceptance}\n\n"
                f"安全检查点：{review.checkpoint_count} 个\n工具修改：{review.summary}"
            )
            keep_button = dialog.addButton("保留本轮", QMessageBox.ButtonRole.AcceptRole)
            undo_button = dialog.addButton("撤销上一步", QMessageBox.ButtonRole.ActionRole)
            rollback_button = dialog.addButton("撤销本轮全部", QMessageBox.ButtonRole.DestructiveRole)
            undo_button.setEnabled(review.checkpoint_count > 0)
            dialog.setDefaultButton(keep_button)
            dialog.exec()
            choice = dialog.clickedButton()
            if choice is keep_button:
                self.agent.commit_transaction()
                self.append_action("agent_commit", review.summary, refresh=False)
            elif choice is rollback_button:
                self.agent.rollback_transaction()
                self.append_action("agent_rollback", review.summary, refresh=False)
                self.append_chat("agent", "本轮修改已撤销，任务书已恢复到操作前。")
                self.refresh_all()
            elif choice is undo_button and self.agent.rollback_last_checkpoint():
                self.append_action("agent_checkpoint_rollback", "用户撤销最近一个安全步骤", refresh=False)
                self.append_chat("agent", "已只撤销最近一个安全步骤，之前的检查点仍然保留。")
                self.refresh_all()
                if not self.agent.has_pending_changes:
                    self.agent.commit_transaction()

    def agent_failed(self, text):
        LOGGER.error("Agent failed: %s", text)
        retained, message = interrupted_run_message(self.agent, text, LOG_PATH)
        if self.agent and not retained:
            self.agent.rollback_transaction()
        if retained:
            self.refresh_all()
            self._agent_attention_message = "当前：检查点已保留，可发送“继续”恢复执行"
            self.agent_panel.set_progress_idle()
            self.agent_current_label.setText(self._agent_attention_message)
        self.append_chat("error", message)

    def agent_finished(self):
        thread = self.agent_thread
        self.set_agent_busy(False)
        self.agent_runtime.detach()
        if thread:
            thread.deleteLater()
        if self.agent:
            persisted = self.agent_session.capture(self.agent)
            self._restored_agent_history = persisted.history
            self._restored_agent_run_state = persisted.run_state
            self._restored_agent_request_context = persisted.request_context
        self.undo_checkpoint_button.setEnabled(bool(self.agent and self.agent.checkpoint_count > 0))
        self.schedule_workspace_save()
        next_prompt = self.agent_runtime.take_next()
        if next_prompt:
            self.prompt.setPlainText(next_prompt)
            QTimer.singleShot(0, self.send_to_agent)
        else:
            self.agent_panel.set_progress_idle()
            if self._agent_attention_message:
                self.agent_current_label.setText(self._agent_attention_message)

    def _render_action(self, name, detail) -> None:
        """Render one technical-history row without changing live Agent state."""
        labels = {
            "get_project_summary": "读取项目",
            "get_chapter_quests": "读取章节任务",
            "list_skills": "查看内置方案",
            "load_skill": "加载内置方案",
            "agent_plan": "建立执行计划",
            "agent_verify": "验收执行结果",
            "agent_repair": "自动修复缺口",
            "agent_checkpoint": "建立安全检查点",
            "agent_checkpoint_rollback": "撤销安全检查点",
            "agent_tool_rejected": "拒绝不安全修改",
            "agent_id_unverified": "ID 未查询提示",
            "create_chapter": "创建章节",
            "add_quest": "添加任务",
            "add_quest_chain": "批量创建任务链",
            "update_quest": "修改任务",
            "get_quest_sections": "读取任务与奖励",
            "replace_quest_sections": "修改任务与奖励",
            "move_quest": "移动任务",
            "connect_quests": "连接任务",
            "apply_dependency_plan": "应用依赖方案",
            "disconnect_quests": "断开任务",
            "remove_quest": "删除任务",
            "search_items": "搜索物品",
            "get_recipe": "读取配方",
            "validate_project": "检查项目",
            "agent_commit": "保留 Agent 修改",
            "agent_rollback": "撤销 Agent 修改",
            "agent_queue": "排队要求",
            "scan_modpack": "扫描整合包",
        }
        full_text = f"{labels.get(name, name)}  {detail}"
        item = QListWidgetItem(full_text[:120])
        item.setToolTip(full_text)
        self.action_list.insertItem(0, item)

    def append_action(self, name, detail, refresh=True):
        self.action_records.append({"name": str(name), "detail": str(detail)})
        self.action_records = self.action_records[-500:]
        self._render_action(name, detail)
        self.update_agent_progress(name, detail)
        if refresh and name in {
            "create_chapter", "add_quest", "add_quest_chain", "update_quest", "replace_quest_sections",
            "move_quest", "connect_quests", "apply_dependency_plan", "disconnect_quests", "remove_quest",
        }:
            self.refresh_all()
        self.schedule_workspace_save()
        if self._live_game_base_payload is not None and not self._applying_shared_events:
            bridge = getattr(self, "bridge_server", None)
            identity = bridge.service.snapshot() if bridge is not None else {}
            if identity.get("project_id") and identity.get("conversation_id"):
                bridge.service.shared_state.append_event(
                    identity["project_id"], identity["conversation_id"],
                    "work.studio", "studio", {"name": str(name), "detail": str(detail)},
                )

    def append_chat(self, role, text):
        self.chat_records.append({"role": str(role), "text": str(text)})
        self.chat_records = self.chat_records[-300:]
        self._render_chat(role, text)
        self.schedule_workspace_save()
        if self._live_game_base_payload is None or self._applying_shared_events:
            return
        bridge = getattr(self, "bridge_server", None)
        identity = bridge.service.snapshot() if bridge is not None else {}
        if not identity.get("project_id") or not identity.get("conversation_id"):
            return
        normalized_role = "user" if role == "user" else "assistant"
        if normalized_role == "user":
            request_id = "studio-" + secrets.token_urlsafe(12)
            self._shared_studio_request_ids.append(request_id)
            kind = "chat.user"
        else:
            request_id = (self._shared_studio_request_ids.pop(0)
                          if self._shared_studio_request_ids else "studio-" + secrets.token_urlsafe(12))
            kind = "chat.assistant"
        bridge.service.shared_state.append_event(
            identity["project_id"], identity["conversation_id"], kind, "studio",
            {"request_id": request_id, "text": str(text), "surface": "studio"},
        )

    def _render_chat(self, role, text):
        safe = escape(str(text)).replace("\n", "<br>")
        if role == "user":
            block = (
                "<table width='100%' cellspacing='0' cellpadding='0'><tr>"
                "<td width='14%'></td><td bgcolor='#d8e9e1' style='padding:10px'>"
                f"<font color='#173f33'><b>你</b><br>{safe}</font></td></tr></table><br>"
            )
        elif role == "error":
            block = (
                "<table width='100%' cellspacing='0' cellpadding='0'><tr>"
                "<td bgcolor='#f4dfd9' style='padding:10px'>"
                f"<font color='#712f25'><b>Agent 出错</b><br>{safe}</font></td>"
                "<td width='10%'></td></tr></table><br>"
            )
        else:
            block = (
                "<table width='100%' cellspacing='0' cellpadding='0'><tr>"
                "<td bgcolor='#e5eee9' style='padding:10px'>"
                f"<font color='#26322c'><b>Agent</b><br>{safe}</font></td>"
                "<td width='10%'></td></tr></table><br>"
            )
        self.chat.append(block)
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())


def run_app():
    logger, log_path = configure_logging(ROOT_DIR)
    install_exception_hooks(logger)
    logger.info("Starting AutoFTBQ Studio; log=%s", log_path)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    apply_light_palette(app)
    if not hasattr(app, "_autoftbq_form_wheel_filter"):
        app._autoftbq_form_wheel_filter = FormWheelNavigationFilter(app)
        app.installEventFilter(app._autoftbq_form_wheel_filter)
    bridge = None
    try:
        bridge = StudioBridgeServer().start()
        logger.info("Game bridge listening on 127.0.0.1:%s", bridge.port)
    except OSError:
        logger.exception("Unable to start the local game bridge")
    window = MainWindow(restore_workspace=True)
    window.attach_game_bridge(bridge)
    window.show()
    QTimer.singleShot(0, window.ensure_ai_setup)
    try:
        return app.exec()
    finally:
        if bridge is not None:
            bridge.stop()


def smoke_test_app() -> int:
    """Initialize the packaged Qt window and bridge without displaying a UI."""
    logger, _log_path = configure_logging(ROOT_DIR)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    apply_light_palette(app)
    bridge = None
    window = None
    try:
        bridge = StudioBridgeServer().start()
        window = MainWindow(restore_workspace=False)
        window.attach_game_bridge(bridge)
        window.show()
        app.processEvents()
        ready = window.windowTitle() == "AutoFTBQ Studio" and bridge.port > 0
        logger.info("Packaged startup smoke test: %s", "passed" if ready else "failed")
        return 0 if ready else 2
    except Exception:
        logger.exception("Packaged startup smoke test failed")
        return 3
    finally:
        if window is not None:
            window.close()
        if bridge is not None:
            bridge.stop()
