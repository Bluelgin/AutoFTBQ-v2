"""Schema-driven task and reward editor shared by manual and Agent workflows."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from snbt_parser import parse_snbt, to_snbt

from ..ftb.schema import (
    CHAPTER_IMAGE_FIELDS,
    CHAPTER_GROUP_FIELDS,
    QUEST_LINK_FIELDS,
    REWARD_TABLE_FIELDS,
    FieldSpec,
    REWARD_TYPES,
    TASK_TYPES,
    TASK_TYPE_CATEGORIES,
    TASK_TYPE_DEFAULTS,
    TASK_TYPE_DESCRIPTIONS,
    object_spec,
)


def _display_type(type_id: str, kind: str) -> str:
    spec = object_spec(kind, type_id)
    return f"{spec.label}  ·  {type_id}"


def _object_summary(raw: dict, kind: str, index: int) -> str:
    type_id = str(raw.get("type") or "")
    title = _display_type(type_id, kind)
    if kind != "task":
        return f"{index}. {title}"
    target = next((raw.get(key) for key in (
        "item", "entity", "entityTypeTag", "dimension", "advancement", "biome",
        "structure", "fluid", "stat", "stage", "to_observe",
    ) if raw.get(key) not in (None, "", {}, [])), "")
    if isinstance(target, dict):
        target = target.get("id") or target.get("fluid") or target.get("item") or ""
    amount = raw.get("count", raw.get("value", ""))
    detail = ""
    if target:
        detail = f"\n{target}"
        if amount not in (None, "", 1):
            detail += f" × {amount}"
    return f"{index}. {title}{detail}"


class ObjectPane(QWidget):
    changed = Signal()

    def __init__(self, kind: str, choose_registry=None, parent=None):
        super().__init__(parent)
        self.setObjectName("schemaEditor")
        self.kind = kind
        self.choose_registry = choose_registry
        self.store = None
        self.quest_id = ""
        self.current_id = ""
        self.current_raw: dict = {}
        self.field_widgets: dict[str, tuple[FieldSpec, QWidget]] = {}
        self.complex_timers: dict[QTextEdit, QTimer] = {}
        self.loading = False

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        sidebar = QFrame()
        sidebar.setObjectName("schemaSidebar")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 6, 0)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        side_layout.addWidget(self.list, 1)
        registry = TASK_TYPES if kind == "task" else REWARD_TYPES
        self.add_type = QComboBox()
        for type_id, spec in registry.items():
            prefix = f"{TASK_TYPE_CATEGORIES.get(type_id, '其他')} · " if kind == "task" else ""
            self.add_type.addItem(prefix + spec.label, type_id)
        side_layout.addWidget(self.add_type)
        actions = QHBoxLayout()
        add = QPushButton("添加")
        add.clicked.connect(self.add_object)
        up = QPushButton("上移")
        up.clicked.connect(lambda: self.move_object(-1))
        down = QPushButton("下移")
        down.clicked.connect(lambda: self.move_object(1))
        remove = QPushButton("删除")
        remove.setObjectName("dangerButton")
        remove.clicked.connect(self.remove_object)
        for button in (add, up, down, remove):
            actions.addWidget(button)
        side_layout.addLayout(actions)
        splitter.addWidget(sidebar)

        details = QWidget()
        details.setObjectName("schemaSurface")
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(6, 0, 0, 0)
        self.type_combo = QComboBox()
        for type_id, spec in registry.items():
            prefix = f"{TASK_TYPE_CATEGORIES.get(type_id, '其他')} · " if kind == "task" else ""
            self.type_combo.addItem(prefix + spec.label, type_id)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("类型"))
        type_row.addWidget(self.type_combo, 1)
        detail_layout.addLayout(type_row)
        self.type_help = QLabel()
        self.type_help.setObjectName("fieldHelp")
        self.type_help.setWordWrap(True)
        detail_layout.addWidget(self.type_help)
        if self.kind == "task":
            condition_help = QLabel("同一任务中的非可选条件默认需要全部完成；勾选“可选”可将该条件排除在必需项之外。")
            condition_help.setObjectName("fieldHelp")
            condition_help.setWordWrap(True)
            detail_layout.addWidget(condition_help)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("schemaScroll")
        self.scroll.viewport().setObjectName("schemaScrollViewport")
        self.scroll.setWidgetResizable(True)
        self.fields_host = QWidget()
        self.fields_host.setObjectName("schemaScrollContent")
        self.fields_form = QFormLayout(self.fields_host)
        self.fields_form.setContentsMargins(4, 8, 8, 8)
        self.fields_form.setVerticalSpacing(7)
        self.scroll.setWidget(self.fields_host)
        detail_layout.addWidget(self.scroll, 2)

        self.raw_toggle = QPushButton("专家模式：显示原始 SNBT")
        self.raw_toggle.setCheckable(True)
        self.raw_toggle.toggled.connect(self._toggle_raw)
        detail_layout.addWidget(self.raw_toggle)
        self.raw_label = QLabel("完整 SNBT（实时同步，扩展字段也会保留）")
        detail_layout.addWidget(self.raw_label)
        self.raw = QTextEdit()
        self.raw.setMaximumHeight(120)
        self.raw.textChanged.connect(self._schedule_raw)
        detail_layout.addWidget(self.raw)
        self.raw_label.hide()
        self.raw.hide()
        self.state = QLabel("请选择一个对象")
        self.state.setObjectName("mainMuted")
        detail_layout.addWidget(self.state)
        self.raw_timer = QTimer(self)
        self.raw_timer.setSingleShot(True)
        self.raw_timer.setInterval(350)
        self.raw_timer.timeout.connect(self._apply_raw)
        splitter.addWidget(details)
        splitter.setSizes([260, 700])

    def _toggle_raw(self, visible: bool) -> None:
        self.raw_label.setVisible(visible)
        self.raw.setVisible(visible)
        self.raw_toggle.setText("专家模式：隐藏原始 SNBT" if visible else "专家模式：显示原始 SNBT")

    @property
    def section(self) -> str:
        return "tasks" if self.kind == "task" else "rewards"

    def set_context(self, store, quest_id: str) -> None:
        self.store = store
        self.quest_id = quest_id
        self.refresh()

    def clear_context(self) -> None:
        self.store = None
        self.quest_id = ""
        self.current_id = ""
        self.list.clear()
        self._clear_fields()
        self.raw.clear()
        self.state.setText("请选择任务节点")

    def _objects(self) -> list[dict]:
        if not self.store or not self.quest_id or not hasattr(self.store, "quest_data"):
            return []
        try:
            values = self.store.quest_data(self.quest_id).get(self.section, [])
        except ValueError:
            return []
        return values if isinstance(values, list) else []

    def refresh(self, preferred_id: str = "") -> None:
        selected = preferred_id or self.current_id
        self.loading = True
        try:
            self.list.clear()
            for index, raw in enumerate(self._objects()):
                if not isinstance(raw, dict):
                    continue
                type_id = str(raw.get("type") or "")
                object_id = str(raw.get("id") or "")
                item = QListWidgetItem(_object_summary(raw, self.kind, index + 1))
                item.setData(Qt.ItemDataRole.UserRole, object_id)
                self.list.addItem(item)
                if object_id == selected:
                    self.list.setCurrentItem(item)
            if self.list.currentItem() is None and self.list.count():
                self.list.setCurrentRow(0)
            if not self.list.count():
                self.current_id = ""
                self._clear_fields()
                self.raw.clear()
                self.state.setText("还没有条件" if self.kind == "task" else "还没有奖励")
        finally:
            self.loading = False
        if self.list.currentItem():
            self._select(self.list.currentItem(), None)

    def _find_raw(self, object_id: str) -> dict:
        return next(
            (raw for raw in self._objects() if isinstance(raw, dict) and str(raw.get("id")) == object_id),
            {},
        )

    def _select(self, current, _previous) -> None:
        if current is None:
            return
        self.current_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        self.current_raw = deepcopy(self._find_raw(self.current_id))
        type_id = str(self.current_raw.get("type") or "")
        self.loading = True
        try:
            index = self.type_combo.findData(type_id)
            if index < 0:
                self.type_combo.addItem(f"扩展类型：{type_id}", type_id)
                index = self.type_combo.count() - 1
            self.type_combo.setCurrentIndex(index)
            self.type_help.setText(TASK_TYPE_DESCRIPTIONS.get(type_id, "") if self.kind == "task" else "")
            self._build_fields(type_id, self.current_raw)
            self.raw.setPlainText(to_snbt(self.current_raw))
            self.state.setText("修改会实时同步，可使用主工具栏撤销")
        finally:
            self.loading = False

    def _clear_fields(self) -> None:
        self.field_widgets.clear()
        self.complex_timers.clear()
        while self.fields_form.rowCount():
            self.fields_form.removeRow(0)

    def _build_fields(self, type_id: str, raw: dict) -> None:
        self._clear_fields()
        spec = object_spec(self.kind, type_id)
        if not spec.fields:
            self.fields_form.addRow(QLabel("此扩展类型没有内置字段描述，请使用下方完整 SNBT 编辑。"))
            return
        for field in spec.fields:
            widget = self._field_widget(field, raw.get(field.key, None), field.key in raw)
            self.field_widgets[field.key] = (field, widget)
            self.fields_form.addRow(field.label, widget)

    def _field_widget(self, field: FieldSpec, value, present: bool) -> QWidget:
        if field.kind in ("bool", "tristate"):
            widget = QComboBox()
            widget.addItem("未设置 / 继承", None)
            widget.addItem("开启", True)
            widget.addItem("关闭", False)
            index = widget.findData(value) if present else 0
            widget.setCurrentIndex(max(0, index))
            widget.currentIndexChanged.connect(lambda _=0, key=field.key, w=widget: self._patch(key, w.currentData()))
            return widget
        if field.kind == "choice":
            widget = QComboBox()
            for choice in field.choices:
                widget.addItem(choice, choice)
            if value not in (None, "") and widget.findData(str(value)) < 0:
                widget.addItem(str(value), str(value))
            index = widget.findData(str(value)) if present else widget.findData(str(field.default))
            widget.setCurrentIndex(max(0, index))
            widget.currentIndexChanged.connect(lambda _=0, key=field.key, w=widget: self._patch(key, w.currentData()))
            return widget
        if field.kind in ("string_list", "compound", "item_stack", "fluid_stack", "int_array"):
            wrapper = QWidget()
            layout = QHBoxLayout(wrapper)
            layout.setContentsMargins(0, 0, 0, 0)
            editor = QTextEdit()
            editor.setMaximumHeight(66)
            if field.kind == "string_list":
                editor.setPlainText("\n".join(str(item) for item in value) if isinstance(value, list) else str(value or ""))
            elif field.kind == "int_array":
                editor.setPlainText(", ".join(str(item) for item in value) if isinstance(value, list) else "")
            elif present:
                editor.setPlainText(to_snbt(value))
            editor.textChanged.connect(lambda key=field.key, spec=field, w=editor: self._schedule_complex(key, spec, w))
            layout.addWidget(editor, 1)
            if field.registry and self.choose_registry:
                choose = QPushButton("选择…")
                choose.clicked.connect(lambda _=False, key=field.key, spec=field, w=editor: self._choose(key, spec, w))
                layout.addWidget(choose)
            return wrapper
        widget = QLineEdit()
        widget.setText("" if value is None else str(value))
        if field.registry and self.choose_registry:
            wrapper = QWidget()
            layout = QHBoxLayout(wrapper)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(widget, 1)
            choose = QPushButton("选择…")
            choose.clicked.connect(lambda _=False, key=field.key, spec=field, w=widget: self._choose(key, spec, w))
            layout.addWidget(choose)
            widget.editingFinished.connect(lambda key=field.key, spec=field, w=widget: self._patch_text(key, spec, w.text()))
            return wrapper
        widget.editingFinished.connect(lambda key=field.key, spec=field, w=widget: self._patch_text(key, spec, w.text()))
        return widget

    def _schedule_complex(self, key: str, field: FieldSpec, editor: QTextEdit) -> None:
        if self.loading:
            return
        timer = self.complex_timers.get(editor)
        if timer is None:
            timer = QTimer(editor)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(lambda: self._patch_complex(key, field, editor.toPlainText()))
            self.complex_timers[editor] = timer
        timer.start()

    def _patch_complex(self, key: str, field: FieldSpec, text: str) -> None:
        try:
            if not text.strip():
                value = None
            elif field.kind == "string_list":
                value = text.splitlines()
            elif field.kind == "int_array":
                value = [int(part.strip()) for part in text.split(",") if part.strip()]
            else:
                value = parse_snbt(text)
            self._patch(key, value)
        except Exception as exc:
            self.state.setText(f"字段尚未同步：{exc}")

    def _patch_text(self, key: str, field: FieldSpec, text: str) -> None:
        try:
            if not text.strip():
                value = None
            elif field.kind in ("int", "long"):
                value = int(text)
            elif field.kind == "double":
                value = float(text)
            else:
                value = text
            self._patch(key, value)
        except ValueError:
            self.state.setText(f"{field.label}需要有效数字")

    def _patch(self, key: str, value) -> None:
        if self.loading or not self.current_id or not hasattr(self.store, "update_quest_object"):
            return
        try:
            self.store.update_quest_object(self.quest_id, self.kind, self.current_id, {key: value})
            self.current_raw = self._find_raw(self.current_id)
            self.loading = True
            self.raw.setPlainText(to_snbt(self.current_raw))
            self.loading = False
            self.state.setText("已实时同步")
            self.changed.emit()
        except Exception as exc:
            self.loading = False
            self.state.setText(f"暂未同步：{exc}")

    def _choose(self, key: str, field: FieldSpec, widget) -> None:
        current = self.current_raw.get(key, "")
        if isinstance(current, dict):
            current = current.get("id") or current.get("fluid") or ""
        selected = self.choose_registry(field.registry, str(current or "")) if self.choose_registry else ""
        if not selected:
            return
        if field.kind in ("item_stack", "fluid_stack"):
            value = {"id": selected, "count": 1} if field.kind == "item_stack" else {"id": selected, "amount": 1000}
            widget.setPlainText(to_snbt(value))
        else:
            widget.setText(selected)
            self._patch_text(key, field, selected)

    def _type_changed(self) -> None:
        if self.loading or not self.current_id:
            return
        type_id = str(self.type_combo.currentData() or "")
        self._patch("type", type_id)
        self.current_raw = self._find_raw(self.current_id)
        self.loading = True
        self._build_fields(type_id, self.current_raw)
        self.loading = False
        self.refresh(self.current_id)

    def _schedule_raw(self) -> None:
        if not self.loading and self.current_id:
            self.raw_timer.start()

    def _apply_raw(self) -> None:
        try:
            value = parse_snbt(self.raw.toPlainText() or "{}")
            if not isinstance(value, dict):
                raise ValueError("对象根节点必须是 compound")
            value.pop("id", None)
            old_keys = set(self.current_raw) - {"id"}
            changes = {key: None for key in old_keys - set(value)}
            changes.update(value)
            self.store.update_quest_object(self.quest_id, self.kind, self.current_id, changes)
            self.current_raw = self._find_raw(self.current_id)
            self._select(self.list.currentItem(), None)
            self.state.setText("完整 SNBT 已实时同步")
            self.changed.emit()
        except Exception as exc:
            self.state.setText(f"SNBT 尚未同步：{exc}")

    def add_object(self) -> None:
        if not self.store or not self.quest_id or not hasattr(self.store, "add_quest_object"):
            self.state.setText("请先打开真实 FTB Quests 任务书")
            return
        type_id = str(self.add_type.currentData() or "")
        defaults = TASK_TYPE_DEFAULTS.get(type_id, {}) if self.kind == "task" else {}
        value = self.store.add_quest_object(self.quest_id, self.kind, type_id, defaults)
        self.refresh(str(value.get("id") or ""))
        self.changed.emit()

    def remove_object(self) -> None:
        if self.current_id and hasattr(self.store, "remove_quest_object"):
            self.store.remove_quest_object(self.quest_id, self.kind, self.current_id)
            self.current_id = ""
            self.refresh()
            self.changed.emit()

    def move_object(self, delta: int) -> None:
        row = self.list.currentRow()
        if row < 0 or not self.current_id or not hasattr(self.store, "move_quest_object"):
            return
        target = max(0, min(row + delta, self.list.count() - 1))
        if target == row:
            return
        self.store.move_quest_object(self.quest_id, self.kind, self.current_id, target)
        self.refresh(self.current_id)
        self.changed.emit()


class QuestSectionsEditor(QTabWidget):
    changed = Signal()

    def __init__(self, choose_registry=None, parent=None):
        super().__init__(parent)
        self.tasks = ObjectPane("task", choose_registry, self)
        self.rewards = ObjectPane("reward", choose_registry, self)
        self.tasks.changed.connect(self.changed.emit)
        self.rewards.changed.connect(self.changed.emit)
        self.addTab(self.tasks, "完成条件")
        self.addTab(self.rewards, "任务奖励")
        self.setTabToolTip(0, "支持物品、维度、生物击杀、进度、统计、位置等 FTB Quests 条件")
        self.setTabToolTip(1, "任务完成后发放的奖励；可同时添加多项")

    def set_context(self, store, quest_id: str) -> None:
        self.tasks.set_context(store, quest_id)
        self.rewards.set_context(store, quest_id)

    def clear_context(self) -> None:
        self.tasks.clear_context()
        self.rewards.clear_context()


class CompoundPropertiesEditor(QWidget):
    """Edit one raw compound through typed fields plus a lossless raw view."""

    changed = Signal()

    def __init__(self, fields: tuple[FieldSpec, ...], choose_registry=None, protected=(), parent=None):
        super().__init__(parent)
        self.setObjectName("schemaEditor")
        self.fields = fields
        self.choose_registry = choose_registry
        self.protected = set(protected)
        self.raw_value: dict = {}
        self.patch_callback = None
        self.loading = False
        self.timers: dict[QTextEdit, QTimer] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        scroll = QScrollArea()
        scroll.setObjectName("schemaScroll")
        scroll.viewport().setObjectName("schemaScrollViewport")
        scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.host.setObjectName("schemaScrollContent")
        self.form = QFormLayout(self.host)
        self.form.setContentsMargins(8, 8, 12, 8)
        self.form.setVerticalSpacing(7)
        scroll.setWidget(self.host)
        splitter.addWidget(scroll)
        raw_side = QWidget()
        raw_side.setObjectName("schemaSurface")
        raw_layout = QVBoxLayout(raw_side)
        raw_layout.setContentsMargins(8, 4, 4, 4)
        raw_layout.addWidget(QLabel("完整属性 SNBT（子对象由专用页面管理）"))
        self.raw = QTextEdit()
        self.raw.textChanged.connect(self._schedule_raw)
        raw_layout.addWidget(self.raw, 1)
        self.state = QLabel("尚未载入")
        self.state.setObjectName("mainMuted")
        raw_layout.addWidget(self.state)
        splitter.addWidget(raw_side)
        splitter.setSizes([620, 380])
        self.raw_timer = QTimer(self)
        self.raw_timer.setSingleShot(True)
        self.raw_timer.setInterval(350)
        self.raw_timer.timeout.connect(self._apply_raw)

    def set_context(self, raw: dict, patch_callback) -> None:
        self.raw_value = deepcopy(raw) if isinstance(raw, dict) else {}
        self.patch_callback = patch_callback
        self._rebuild()

    def clear_context(self, message: str = "请先打开真实 FTB Quests 任务书") -> None:
        self.raw_value = {}
        self.patch_callback = None
        self.loading = True
        self._clear_form()
        self.raw.clear()
        self.loading = False
        self.state.setText(message)

    def _editable_raw(self) -> dict:
        return {key: deepcopy(value) for key, value in self.raw_value.items() if key not in self.protected}

    def _clear_form(self) -> None:
        self.timers.clear()
        while self.form.rowCount():
            self.form.removeRow(0)

    def _rebuild(self) -> None:
        self.loading = True
        try:
            self._clear_form()
            for field in self.fields:
                widget = self._make_widget(field, self.raw_value.get(field.key), field.key in self.raw_value)
                self.form.addRow(field.label, widget)
            self.raw.setPlainText(to_snbt(self._editable_raw()))
            self.state.setText("修改会实时同步，可使用主工具栏撤销")
        finally:
            self.loading = False

    def _make_widget(self, field: FieldSpec, value, present: bool) -> QWidget:
        if field.kind in ("bool", "tristate"):
            widget = QComboBox()
            widget.addItem("未设置 / 继承", None)
            widget.addItem("开启", True)
            widget.addItem("关闭", False)
            widget.setCurrentIndex(max(0, widget.findData(value) if present else 0))
            widget.currentIndexChanged.connect(lambda _=0, key=field.key, w=widget: self._patch({key: w.currentData()}))
            return widget
        if field.kind == "choice":
            widget = QComboBox()
            for choice in field.choices:
                widget.addItem(choice, choice)
            if present and value not in (None, "") and widget.findData(str(value)) < 0:
                widget.addItem(str(value), str(value))
            index = widget.findData(str(value)) if present else widget.findData(str(field.default))
            widget.setCurrentIndex(max(0, index))
            widget.currentIndexChanged.connect(lambda _=0, key=field.key, w=widget: self._patch({key: w.currentData()}))
            return widget
        if field.kind in ("string_list", "compound", "item_stack", "fluid_stack", "int_array"):
            editor = QTextEdit()
            editor.setMaximumHeight(64)
            if field.kind == "string_list":
                editor.setPlainText("\n".join(str(item) for item in value) if isinstance(value, list) else str(value or ""))
            elif field.kind == "int_array":
                editor.setPlainText(", ".join(str(item) for item in value) if isinstance(value, list) else "")
            elif present:
                editor.setPlainText(to_snbt(value))
            editor.textChanged.connect(lambda key=field.key, spec=field, w=editor: self._schedule_complex(key, spec, w))
            return editor
        line = QLineEdit("" if value is None else str(value))
        line.editingFinished.connect(lambda key=field.key, spec=field, w=line: self._patch_text(key, spec, w.text()))
        if not field.registry or not self.choose_registry:
            return line
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line, 1)
        choose = QPushButton("选择…")
        choose.clicked.connect(lambda _=False, key=field.key, spec=field, w=line: self._choose(key, spec, w))
        row.addWidget(choose)
        return wrapper

    def _schedule_complex(self, key: str, field: FieldSpec, editor: QTextEdit) -> None:
        if self.loading:
            return
        timer = self.timers.get(editor)
        if timer is None:
            timer = QTimer(editor)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(lambda: self._patch_complex(key, field, editor.toPlainText()))
            self.timers[editor] = timer
        timer.start()

    def _patch_complex(self, key: str, field: FieldSpec, text: str) -> None:
        try:
            if not text.strip():
                value = None
            elif field.kind == "string_list":
                value = text.splitlines()
            elif field.kind == "int_array":
                value = [int(part.strip()) for part in text.split(",") if part.strip()]
            else:
                value = parse_snbt(text)
            self._patch({key: value})
        except Exception as exc:
            self.state.setText(f"字段尚未同步：{exc}")

    def _patch_text(self, key: str, field: FieldSpec, text: str) -> None:
        try:
            if not text.strip():
                value = None
            elif field.kind in ("int", "long"):
                value = int(text)
            elif field.kind == "double":
                value = float(text)
            else:
                value = text
            self._patch({key: value})
        except ValueError:
            self.state.setText(f"{field.label}需要有效数字")

    def _choose(self, key: str, field: FieldSpec, line: QLineEdit) -> None:
        selected = self.choose_registry(field.registry, line.text()) if self.choose_registry else ""
        if selected:
            line.setText(selected)
            self._patch({key: selected})

    def _patch(self, changes: dict) -> None:
        if self.loading or self.patch_callback is None:
            return
        try:
            updated = self.patch_callback(changes)
            if isinstance(updated, dict):
                self.raw_value = deepcopy(updated)
            self.loading = True
            self.raw.setPlainText(to_snbt(self._editable_raw()))
            self.loading = False
            self.state.setText("已实时同步")
            self.changed.emit()
        except Exception as exc:
            self.loading = False
            self.state.setText(f"暂未同步：{exc}")

    def _schedule_raw(self) -> None:
        if not self.loading and self.patch_callback is not None:
            self.raw_timer.start()

    def _apply_raw(self) -> None:
        try:
            value = parse_snbt(self.raw.toPlainText() or "{}")
            if not isinstance(value, dict):
                raise ValueError("属性根节点必须是 compound")
            if self.protected.intersection(value):
                raise ValueError("子对象不能在此页面修改")
            old = self._editable_raw()
            changes = {key: None for key in set(old) - set(value)}
            changes.update(value)
            self._patch(changes)
            self.state.setText("完整属性 SNBT 已实时同步")
        except Exception as exc:
            self.state.setText(f"SNBT 尚未同步：{exc}")


class DocumentObjectPane(ObjectPane):
    """Schema object list backed by a list inside a supporting SNBT document."""

    def __init__(self, kind: str, choose_registry=None, parent=None):
        self.document_path = ""
        self.document_section = ""
        super().__init__(kind, choose_registry, parent)

    @property
    def section(self) -> str:
        return self.document_section

    def set_document_context(self, store, path: str, section: str) -> None:
        self.store = store
        self.document_path = path
        self.document_section = section
        self.quest_id = path
        self.refresh()

    def _objects(self) -> list[dict]:
        if not self.store or not self.document_path or not hasattr(self.store, "document_objects"):
            return []
        return self.store.document_objects(self.document_path, self.document_section)

    def _patch(self, key: str, value) -> None:
        if self.loading or not self.current_id or not hasattr(self.store, "update_document_object"):
            return
        try:
            self.store.update_document_object(
                self.document_path, self.document_section, self.current_id, {key: value},
            )
            self.current_raw = self._find_raw(self.current_id)
            self.loading = True
            self.raw.setPlainText(to_snbt(self.current_raw))
            self.loading = False
            self.state.setText("已实时同步")
            self.changed.emit()
        except Exception as exc:
            self.loading = False
            self.state.setText(f"暂未同步：{exc}")

    def _apply_raw(self) -> None:
        try:
            value = parse_snbt(self.raw.toPlainText() or "{}")
            if not isinstance(value, dict):
                raise ValueError("对象根节点必须是 compound")
            value.pop("id", None)
            old_keys = set(self.current_raw) - {"id"}
            changes = {key: None for key in old_keys - set(value)}
            changes.update(value)
            self.store.update_document_object(
                self.document_path, self.document_section, self.current_id, changes,
            )
            self.current_raw = self._find_raw(self.current_id)
            self._select(self.list.currentItem(), None)
            self.state.setText("完整 SNBT 已实时同步")
            self.changed.emit()
        except Exception as exc:
            self.state.setText(f"SNBT 尚未同步：{exc}")

    def add_object(self) -> None:
        if not self.store or not self.document_path or not hasattr(self.store, "add_document_object"):
            self.state.setText("请先打开奖励表")
            return
        type_id = str(self.add_type.currentData() or "")
        value = self.store.add_document_object(
            self.document_path, self.document_section, {"type": type_id, "weight": 1.0},
        )
        self.refresh(str(value.get("id") or ""))
        self.changed.emit()

    def remove_object(self) -> None:
        if self.current_id and hasattr(self.store, "remove_document_object"):
            self.store.remove_document_object(
                self.document_path, self.document_section, self.current_id,
            )
            self.current_id = ""
            self.refresh()
            self.changed.emit()

    def move_object(self, delta: int) -> None:
        row = self.list.currentRow()
        if row < 0 or not self.current_id or not hasattr(self.store, "move_document_object"):
            return
        target = max(0, min(row + delta, self.list.count() - 1))
        if target != row:
            self.store.move_document_object(
                self.document_path, self.document_section, self.current_id, target,
            )
            self.refresh(self.current_id)
            self.changed.emit()


class ChapterGroupsEditor(QWidget):
    changed = Signal()

    def __init__(self, choose_registry=None, parent=None):
        super().__init__(parent)
        self.store = None
        self.current_id = ""
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, callback in (
            ("添加", self.add_group), ("上移", lambda: self.move_group(-1)),
            ("下移", lambda: self.move_group(1)), ("删除", self.remove_group),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        left.addLayout(row)
        left_host = QWidget()
        left_host.setLayout(left)
        root.addWidget(left_host, 1)
        self.properties = CompoundPropertiesEditor(
            CHAPTER_GROUP_FIELDS, choose_registry, protected=("id",), parent=self,
        )
        self.properties.changed.connect(self._properties_changed)
        root.addWidget(self.properties, 3)

    def set_store(self, store) -> None:
        self.store = store if hasattr(store, "document_objects") else None
        self.refresh()

    def refresh(self, preferred: str = "") -> None:
        selected = preferred or self.current_id
        self.list.clear()
        if self.store is None:
            self.properties.clear_context()
            return
        for raw in self.store.document_objects("chapter_groups.snbt", "chapter_groups"):
            object_id = str(raw.get("id") or "")
            item = QListWidgetItem(str(raw.get("title") or f"未命名分组 {object_id}"))
            item.setData(Qt.ItemDataRole.UserRole, object_id)
            self.list.addItem(item)
            if object_id == selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        if not self.list.count():
            self.current_id = ""
            self.properties.clear_context("还没有章节分组")

    def _select(self, current, _previous) -> None:
        if current is None or self.store is None:
            return
        self.current_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        raw = next(
            (value for value in self.store.document_objects("chapter_groups.snbt", "chapter_groups") if str(value.get("id")) == self.current_id),
            {},
        )
        self.properties.set_context(
            raw,
            lambda changes: self.store.update_document_object(
                "chapter_groups.snbt", "chapter_groups", self.current_id, changes,
            ),
        )

    def add_group(self) -> None:
        if self.store is None:
            return
        value = self.store.create_chapter_group("新章节分组")
        self.refresh(str(value["id"]))
        self.changed.emit()

    def remove_group(self) -> None:
        if self.store and self.current_id:
            self.store.remove_chapter_group(self.current_id)
            self.current_id = ""
            self.refresh()
            self.changed.emit()

    def move_group(self, delta: int) -> None:
        row = self.list.currentRow()
        if self.store is None or row < 0 or not self.current_id:
            return
        target = max(0, min(row + delta, self.list.count() - 1))
        if target != row:
            self.store.move_document_object("chapter_groups.snbt", "chapter_groups", self.current_id, target)
            self.refresh(self.current_id)
            self.changed.emit()

    def _properties_changed(self) -> None:
        self.refresh(self.current_id)
        self.changed.emit()


class RewardTablesEditor(QWidget):
    changed = Signal()

    def __init__(self, choose_registry=None, parent=None):
        super().__init__(parent)
        self.store = None
        self.current_path = ""
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        left.addWidget(self.list, 1)
        add = QPushButton("新建奖励表")
        add.clicked.connect(self.add_table)
        remove = QPushButton("删除奖励表")
        remove.setObjectName("dangerButton")
        remove.clicked.connect(self.remove_table)
        left.addWidget(add)
        left.addWidget(remove)
        left_host = QWidget()
        left_host.setLayout(left)
        root.addWidget(left_host, 1)
        right = QTabWidget()
        self.properties = CompoundPropertiesEditor(
            REWARD_TABLE_FIELDS, choose_registry, protected=("id", "rewards"), parent=self,
        )
        self.properties.changed.connect(self._properties_changed)
        right.addTab(self.properties, "奖励表属性")
        self.rewards = DocumentObjectPane("reward", choose_registry, self)
        self.rewards.changed.connect(self.changed.emit)
        right.addTab(self.rewards, "奖励内容")
        root.addWidget(right, 4)

    def set_store(self, store) -> None:
        self.store = store if hasattr(store, "list_reward_tables") else None
        self.refresh()

    def refresh(self, preferred: str = "") -> None:
        selected = preferred or self.current_path
        self.list.clear()
        if self.store is None:
            self.properties.clear_context()
            self.rewards.clear_context()
            return
        for table in self.store.list_reward_tables():
            path, raw = table["path"], table["data"]
            item = QListWidgetItem(str(raw.get("title") or path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.list.addItem(item)
            if path == selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        if not self.list.count():
            self.current_path = ""
            self.properties.clear_context("还没有奖励表")
            self.rewards.clear_context()

    def _select(self, current, _previous) -> None:
        if current is None or self.store is None:
            return
        self.current_path = str(current.data(Qt.ItemDataRole.UserRole) or "")
        raw = self.store.document(self.current_path)
        self.properties.set_context(
            raw,
            lambda changes: self.store.update_document(self.current_path, changes),
        )
        self.rewards.set_document_context(self.store, self.current_path, "rewards")

    def add_table(self) -> None:
        if self.store is not None:
            table = self.store.create_reward_table("新奖励表")
            self.refresh(table["path"])
            self.changed.emit()

    def remove_table(self) -> None:
        if self.store and self.current_path:
            self.store.remove_document(self.current_path)
            self.current_path = ""
            self.refresh()
            self.changed.emit()

    def _properties_changed(self) -> None:
        self.refresh(self.current_path)
        self.changed.emit()


class ChapterObjectListEditor(QWidget):
    changed = Signal()

    def __init__(self, kind: str, fields: tuple[FieldSpec, ...], choose_registry=None, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.store = None
        self.chapter_id = ""
        self.current_id = ""
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        left.addWidget(self.list, 1)
        add = QPushButton("添加图片" if kind == "image" else "添加跳转链接")
        add.clicked.connect(self.add_object)
        remove = QPushButton("删除")
        remove.setObjectName("dangerButton")
        remove.clicked.connect(self.remove_object)
        left.addWidget(add)
        left.addWidget(remove)
        left_host = QWidget()
        left_host.setLayout(left)
        root.addWidget(left_host, 1)
        self.properties = CompoundPropertiesEditor(fields, choose_registry, protected=("id",), parent=self)
        self.properties.changed.connect(self._properties_changed)
        root.addWidget(self.properties, 4)

    @property
    def section(self) -> str:
        return "images" if self.kind == "image" else "quest_links"

    def set_context(self, store, chapter_id: str) -> None:
        self.store = store if hasattr(store, "chapter_data") else None
        self.chapter_id = chapter_id
        self.refresh()

    def _objects(self) -> list[dict]:
        if self.store is None or not self.chapter_id:
            return []
        values = self.store.chapter_data(self.chapter_id).get(self.section, [])
        return values if isinstance(values, list) else []

    def refresh(self, preferred: str = "") -> None:
        selected = preferred or self.current_id
        self.list.clear()
        for index, raw in enumerate(self._objects()):
            object_id = str(raw.get("id") or "")
            name = raw.get("image") if self.kind == "image" else raw.get("linked_quest")
            item = QListWidgetItem(str(name or f"{self.kind} #{index + 1}"))
            item.setData(Qt.ItemDataRole.UserRole, object_id)
            self.list.addItem(item)
            if object_id == selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        if not self.list.count():
            self.current_id = ""
            self.properties.clear_context("还没有章节图片" if self.kind == "image" else "还没有跳转链接")

    def _select(self, current, _previous) -> None:
        if current is None:
            return
        self.current_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        raw = next((value for value in self._objects() if str(value.get("id")) == self.current_id), {})
        self.properties.set_context(
            raw,
            lambda changes: self.store.update_chapter_object(
                self.chapter_id, self.kind, self.current_id, changes,
            ),
        )

    def add_object(self) -> None:
        if self.store is None or not self.chapter_id:
            return
        defaults = (
            {"image": "minecraft:textures/item/book.png", "x": 0.0, "y": 0.0, "width": 2.0, "height": 2.0}
            if self.kind == "image" else
            {"linked_quest": "", "x": 0.0, "y": 0.0, "shape": "circle", "size": 1.0}
        )
        value = self.store.add_chapter_object(self.chapter_id, self.kind, defaults)
        self.refresh(str(value["id"]))
        self.changed.emit()

    def remove_object(self) -> None:
        if self.store and self.current_id:
            self.store.remove_chapter_object(self.chapter_id, self.kind, self.current_id)
            self.current_id = ""
            self.refresh()
            self.changed.emit()

    def _properties_changed(self) -> None:
        self.refresh(self.current_id)
        self.changed.emit()


class ChapterCanvasObjectsEditor(QTabWidget):
    changed = Signal()

    def __init__(self, choose_registry=None, parent=None):
        super().__init__(parent)
        self.images = ChapterObjectListEditor("image", CHAPTER_IMAGE_FIELDS, choose_registry, self)
        self.links = ChapterObjectListEditor("link", QUEST_LINK_FIELDS, choose_registry, self)
        self.images.changed.connect(self.changed.emit)
        self.links.changed.connect(self.changed.emit)
        self.addTab(self.images, "章节图片")
        self.addTab(self.links, "任务跳转链接")

    def set_context(self, store, chapter_id: str) -> None:
        self.images.set_context(store, chapter_id)
        self.links.set_context(store, chapter_id)


class TranslationsEditor(QWidget):
    """Native FTB Quests locale editor backed by split lang documents."""

    changed = Signal()
    OBJECT_TYPES = (
        ("章节", "chapter"), ("任务", "quest"), ("条件", "task"), ("奖励", "reward"),
        ("任务跳转", "quest_link"), ("章节图片", "image"),
        ("奖励表", "reward_table"), ("章节分组", "chapter_group"),
    )
    FIELDS = (
        ("标题", "title"), ("任务副标题", "quest_subtitle"),
        ("任务描述", "quest_desc"), ("章节副标题", "chapter_subtitle"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = None
        self.loading = False
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self.entries = QListWidget()
        self.entries.currentItemChanged.connect(self._select_entry)
        root.addWidget(self.entries, 2)
        details = QWidget()
        form = QFormLayout(details)
        self.locale = QComboBox()
        self.locale.setEditable(True)
        self.locale.activated.connect(lambda _=0: self.refresh_entries())
        if self.locale.lineEdit():
            self.locale.lineEdit().editingFinished.connect(self.refresh_entries)
        self.object_type = QComboBox()
        for label, value in self.OBJECT_TYPES:
            self.object_type.addItem(label, value)
        self.object_type.currentIndexChanged.connect(self._refresh_objects)
        self.object_id = QComboBox()
        self.object_id.setEditable(True)
        self.field = QComboBox()
        for label, value in self.FIELDS:
            self.field.addItem(label, value)
        self.value = QTextEdit()
        self.value.setMinimumHeight(150)
        self.value.textChanged.connect(self._schedule_apply)
        self.state = QLabel("选择语言和对象后即可编辑")
        self.state.setObjectName("mainMuted")
        form.addRow("语言", self.locale)
        form.addRow("对象类型", self.object_type)
        form.addRow("对象", self.object_id)
        form.addRow("翻译字段", self.field)
        form.addRow("内容", self.value)
        form.addRow(self.state)
        root.addWidget(details, 3)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self._apply)

    def set_store(self, store) -> None:
        resolved = store if hasattr(store, "translation_entries") else None
        if resolved is self.store:
            self._refresh_objects()
            self.refresh_entries()
            return
        self.store = resolved
        self.loading = True
        self.locale.clear()
        if self.store is not None:
            locales = self.store.list_locales()
            fallback = str(self.store.document("data.snbt").get("fallback_locale") or "en_us")
            for locale in locales or [fallback]:
                self.locale.addItem(locale)
            if fallback not in locales:
                self.locale.addItem(fallback)
            self.locale.setCurrentText(fallback)
        self.loading = False
        self._refresh_objects()
        self.refresh_entries()

    def _all_objects(self, object_type: str) -> list[tuple[str, str]]:
        if self.store is None:
            return []
        values = []
        for chapter in self.store.project.chapters:
            if object_type == "chapter":
                values.append((chapter.id, chapter.title))
            for quest in chapter.quests:
                if object_type == "quest":
                    values.append((quest.id, quest.title))
                raw = self.store.quest_data(quest.id)
                section = "tasks" if object_type == "task" else "rewards" if object_type == "reward" else ""
                if section:
                    for index, child in enumerate(raw.get(section, [])):
                        if isinstance(child, dict) and child.get("id"):
                            values.append((str(child["id"]), f"{quest.title} / {child.get('type', section)} {index + 1}"))
            raw_chapter = self.store.chapter_data(chapter.id)
            section = "quest_links" if object_type == "quest_link" else "images" if object_type == "image" else ""
            if section:
                for index, child in enumerate(raw_chapter.get(section, [])):
                    if isinstance(child, dict) and child.get("id"):
                        values.append((str(child["id"]), f"{chapter.title} / {object_type} {index + 1}"))
        if object_type == "reward_table":
            values.extend(
                (str(table["data"].get("id") or ""), str(table["data"].get("title") or table["path"]))
                for table in self.store.list_reward_tables() if table["data"].get("id")
            )
        elif object_type == "chapter_group":
            values.extend(
                (str(raw.get("id") or ""), str(raw.get("title") or raw.get("id")))
                for raw in self.store.document_objects("chapter_groups.snbt", "chapter_groups") if raw.get("id")
            )
        return values

    def _refresh_objects(self) -> None:
        selected = str(self.object_id.currentData() or self.object_id.currentText() or "")
        was_loading = self.loading
        self.loading = True
        self.object_id.clear()
        for object_id, label in self._all_objects(str(self.object_type.currentData() or "")):
            self.object_id.addItem(f"{label} · {object_id}", object_id)
            if object_id == selected:
                self.object_id.setCurrentIndex(self.object_id.count() - 1)
        self.loading = was_loading

    def refresh_entries(self) -> None:
        if self.loading:
            return
        self.entries.clear()
        if self.store is None:
            self.value.clear()
            self.state.setText("真实任务书加载后可编辑多语言文本")
            return
        try:
            for key, value in sorted(self.store.translation_entries(self.locale.currentText()).items()):
                item = QListWidgetItem(key)
                item.setData(Qt.ItemDataRole.UserRole, (key, value))
                self.entries.addItem(item)
            self.state.setText(f"已读取 {self.entries.count()} 条翻译，修改内容会实时同步")
        except Exception as exc:
            self.state.setText(str(exc))

    def _select_entry(self, current, _previous) -> None:
        if current is None:
            return
        key, value = current.data(Qt.ItemDataRole.UserRole)
        parts = str(key).split(".", 2)
        if len(parts) != 3:
            self.state.setText("这是扩展翻译键，将保留但不提供结构化编辑")
            return
        self.loading = True
        type_index = self.object_type.findData(parts[0])
        if type_index >= 0:
            self.object_type.setCurrentIndex(type_index)
            self._refresh_objects()
        object_index = self.object_id.findData(parts[1])
        if object_index >= 0:
            self.object_id.setCurrentIndex(object_index)
        else:
            self.object_id.setCurrentText(parts[1])
        field_index = self.field.findData(parts[2])
        if field_index >= 0:
            self.field.setCurrentIndex(field_index)
        self.value.setPlainText("\n".join(value) if isinstance(value, list) else str(value))
        self.loading = False

    def _schedule_apply(self) -> None:
        if not self.loading and self.store is not None:
            self.timer.start()

    def _apply(self) -> None:
        object_id = str(self.object_id.currentData() or self.object_id.currentText() or "").strip()
        if not object_id:
            self.state.setText("请先选择翻译对象")
            return
        field = str(self.field.currentData() or "title")
        text = self.value.toPlainText()
        value = text.splitlines() if field in {"quest_desc", "chapter_subtitle"} else text
        try:
            self.store.update_translation(
                self.locale.currentText(), str(self.object_type.currentData()), object_id, field, value,
            )
            self.state.setText("翻译已实时同步")
            self.changed.emit()
        except Exception as exc:
            self.state.setText(f"暂未同步：{exc}")
