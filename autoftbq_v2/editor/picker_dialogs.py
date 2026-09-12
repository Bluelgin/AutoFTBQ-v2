"""Searchable item and registry picker dialogs."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)

from ..infrastructure.asset_index import AssetIndex
from ..infrastructure.workers import IconPrewarmWorker


class ItemPickerDialog(QDialog):
    RESULT_LIMIT = 80

    def __init__(self, asset_index: AssetIndex, selected_id: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("pickerDialog")
        self.asset_index = asset_index
        self.selected_id = selected_id
        self.setWindowTitle("选择目标物品 ID")
        self.resize(720, 540)
        layout = QVBoxLayout(self)
        hint = QLabel("搜索物品名称或命名空间 ID。选中结果后按需解析对应图标。")
        hint.setObjectName("pickerHint")
        layout.addWidget(hint)
        self.search = QLineEdit()
        self.search.setObjectName("pickerSearch")
        self.search.setPlaceholderText("例如：齿轮、create:shaft、minecraft:iron_ingot")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_results)
        layout.addWidget(self.search)

        self.results = QListWidget()
        self.results.setObjectName("pickerResults")
        self.results.setIconSize(QSize(34, 34))
        self.results.currentItemChanged.connect(self.update_preview)
        self.results.itemDoubleClicked.connect(lambda _item: self.accept_selection())
        layout.addWidget(self.results, 1)

        preview_row = QHBoxLayout()
        self.preview_icon = QLabel("无图标")
        self.preview_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_icon.setFixedSize(58, 58)
        self.preview_icon.setObjectName("itemPreview")
        self.preview_text = QLabel("请选择一个物品")
        self.preview_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview_row.addWidget(self.preview_icon)
        preview_row.addWidget(self.preview_text, 1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        choose = QPushButton("使用此 ID")
        choose.setObjectName("primaryButton")
        choose.clicked.connect(self.accept_selection)
        preview_row.addWidget(cancel)
        preview_row.addWidget(choose)
        layout.addLayout(preview_row)
        if selected_id:
            self.search.setText(selected_id)
        else:
            self.refresh_results()

    def refresh_results(self):
        query = self.search.text().strip().casefold()
        matches = []
        for asset in self.asset_index.items.values():
            searchable = f"{asset.item_id} {asset.name}".casefold()
            if query and query not in searchable:
                continue
            rank = 0 if asset.item_id.casefold().startswith(query) else 1
            matches.append((rank, asset.item_id, asset))
        matches.sort(key=lambda value: (value[0], value[1]))
        self.results.clear()
        selected_item = None
        for _rank, _item_id, asset in matches[: self.RESULT_LIMIT]:
            item = QListWidgetItem(f"{asset.name}\n{asset.item_id}")
            item.setData(Qt.ItemDataRole.UserRole, asset.item_id)
            self.results.addItem(item)
            if asset.item_id == self.selected_id:
                selected_item = item
        if selected_item is not None:
            self.results.setCurrentItem(selected_item)
        elif self.results.count():
            self.results.setCurrentRow(0)
        self.setWindowTitle(f"选择目标物品 ID · {len(matches)} 个结果")

    def update_preview(self, current, _previous=None):
        if current is None:
            self.preview_icon.setPixmap(QPixmap())
            self.preview_icon.setText("无图标")
            self.preview_text.setText("没有匹配结果")
            return
        item_id = current.data(Qt.ItemDataRole.UserRole)
        asset = self.asset_index.items[item_id]
        icon_path = self.asset_index.icon_for(item_id)
        status_reader = getattr(self.asset_index, "icon_status_text", None)
        status = status_reader(item_id) if callable(status_reader) else ""
        self.preview_text.setText(f"{asset.name}\n{item_id}" + (f"\n{status}" if status else ""))
        current.setToolTip(status)
        pixmap = QPixmap(icon_path) if icon_path else QPixmap()
        if pixmap.isNull():
            self.preview_icon.setPixmap(QPixmap())
            self.preview_icon.setText("无图标")
        else:
            self.preview_icon.setText("")
            self.preview_icon.setPixmap(
                pixmap.scaled(
                    48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            current.setIcon(QIcon(icon_path))

    def accept_selection(self):
        current = self.results.currentItem()
        if current is None:
            return
        self.selected_id = current.data(Qt.ItemDataRole.UserRole)
        self.accept()


class IconPickerDialog(QDialog):
    """Searchable icon grid that renders only visible results in the background."""

    RESULT_LIMIT = 600
    BATCH_SIZE = 24

    def __init__(
        self, asset_index: AssetIndex, selected_id: str = "", parent=None, icon_loader=None,
    ):
        super().__init__(parent)
        self.setObjectName("pickerDialog")
        self.asset_index = asset_index
        self.selected_id = str(selected_id or "")
        self.icon_loader = icon_loader
        self._items_by_id: dict[str, QListWidgetItem] = {}
        self._requested_ids: set[str] = set()
        self._pending_ids: list[str] = []
        self._worker = None
        self._closing = False
        self.setWindowTitle("选择任务图标")
        self.resize(820, 620)

        layout = QVBoxLayout(self)
        self.hint = QLabel("搜索名称、模组命名空间或物品 ID；当前可见图标会在后台准备。")
        self.hint.setObjectName("pickerHint")
        layout.addWidget(self.hint)
        self.search = QLineEdit()
        self.search.setObjectName("pickerSearch")
        self.search.setPlaceholderText("例如：下界之星、cataclysm、minecraft:nether_star")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_results)
        layout.addWidget(self.search)

        self.results = QListWidget()
        self.results.setObjectName("iconPickerResults")
        self.results.setViewMode(QListView.ViewMode.IconMode)
        self.results.setResizeMode(QListView.ResizeMode.Adjust)
        self.results.setMovement(QListView.Movement.Static)
        self.results.setWrapping(True)
        self.results.setWordWrap(True)
        self.results.setIconSize(QSize(44, 44))
        self.results.setGridSize(QSize(145, 96))
        self.results.currentItemChanged.connect(self.update_preview)
        self.results.itemDoubleClicked.connect(lambda _item: self.accept_selection())
        self.results.verticalScrollBar().valueChanged.connect(self.schedule_visible_icons)
        layout.addWidget(self.results, 1)

        footer = QHBoxLayout()
        self.preview_icon = QLabel("无图标")
        self.preview_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_icon.setFixedSize(58, 58)
        self.preview_icon.setObjectName("itemPreview")
        self.preview_text = QLabel("请选择一个图标")
        self.preview_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        footer.addWidget(self.preview_icon)
        footer.addWidget(self.preview_text, 1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        choose = QPushButton("使用此图标")
        choose.setObjectName("primaryButton")
        choose.clicked.connect(self.accept_selection)
        footer.addWidget(cancel)
        footer.addWidget(choose)
        layout.addLayout(footer)

        if self.selected_id:
            self.search.setText(self.selected_id)
        else:
            self.refresh_results()

    def refresh_results(self) -> None:
        query = self.search.text().strip().casefold()
        matches = []
        for asset in self.asset_index.items.values():
            searchable = f"{asset.item_id} {asset.name}".casefold()
            if query and query not in searchable:
                continue
            rank = -1 if asset.item_id == self.selected_id else (
                0 if asset.item_id.casefold().startswith(query) else 1
            )
            matches.append((rank, str(asset.name).casefold(), asset.item_id, asset))
        matches.sort(key=lambda value: (value[0], value[1], value[2]))
        self.results.clear()
        self._items_by_id.clear()
        selected_item = None
        for _rank, _name, _item_id, asset in matches[: self.RESULT_LIMIT]:
            item = QListWidgetItem(f"{asset.name}\n{asset.item_id}")
            item.setData(Qt.ItemDataRole.UserRole, asset.item_id)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            item.setToolTip(f"{asset.name}\n{asset.item_id}")
            self.results.addItem(item)
            self._items_by_id[asset.item_id] = item
            self._apply_cached_icon(asset.item_id, item)
            if asset.item_id == self.selected_id:
                selected_item = item
        if selected_item is not None:
            self.results.setCurrentItem(selected_item)
        elif self.results.count():
            self.results.setCurrentRow(0)
        shown = min(len(matches), self.RESULT_LIMIT)
        suffix = f"（显示前 {shown} 个，请搜索以缩小范围）" if len(matches) > shown else ""
        self.setWindowTitle(f"选择任务图标 · {len(matches)} 个结果{suffix}")
        QTimer.singleShot(0, self.schedule_visible_icons)

    def _pixmap(self, path: str, size: int) -> QPixmap:
        if self.icon_loader:
            return self.icon_loader(path, size)
        pixmap = QPixmap(path)
        return pixmap.scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ) if not pixmap.isNull() else pixmap

    def _apply_cached_icon(self, item_id: str, item=None) -> bool:
        path = self.asset_index.cached_icon_for(item_id)
        if not path:
            return False
        pixmap = self._pixmap(path, 44)
        if pixmap.isNull():
            return False
        target = item or self._items_by_id.get(item_id)
        if target is not None:
            target.setIcon(QIcon(pixmap))
        return True

    def schedule_visible_icons(self, *_args) -> None:
        if not self._closing:
            QTimer.singleShot(0, self._queue_visible_icons)

    def _queue_visible_icons(self) -> None:
        if self._closing or not self.results.count():
            return
        viewport_rect = self.results.viewport().rect()
        visible_ids = []
        for index in range(self.results.count()):
            item = self.results.item(index)
            if index >= 36 and not self.results.visualItemRect(item).intersects(viewport_rect):
                continue
            item_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if item_id and not self._apply_cached_icon(item_id, item):
                visible_ids.append(item_id)
        self._queue_ids(visible_ids)

    def _queue_ids(self, item_ids, *, priority=False) -> None:
        fresh = [
            item_id for item_id in item_ids
            if item_id and item_id not in self._requested_ids
        ]
        if not fresh:
            return
        self._requested_ids.update(fresh)
        self._pending_ids = fresh + self._pending_ids if priority else self._pending_ids + fresh
        self._start_next_batch()

    def _start_next_batch(self) -> None:
        if self._closing or self._worker is not None or not self._pending_ids:
            return
        batch = self._pending_ids[: self.BATCH_SIZE]
        del self._pending_ids[: self.BATCH_SIZE]
        worker = IconPrewarmWorker(self.asset_index, batch, parent=self)
        worker.icon_ready.connect(self._icon_ready)
        worker.finished.connect(lambda source=worker: self._batch_finished(source))
        self._worker = worker
        worker.start()

    def _icon_ready(self, item_id: str, path: str) -> None:
        if self._closing:
            return
        item = self._items_by_id.get(item_id)
        if item is not None:
            pixmap = self._pixmap(path, 44)
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap))
        current = self.results.currentItem()
        if current is not None and current.data(Qt.ItemDataRole.UserRole) == item_id:
            self.update_preview(current)

    def _batch_finished(self, source) -> None:
        if source is self._worker:
            self._worker = None
        source.deleteLater()
        self._start_next_batch()

    def update_preview(self, current, _previous=None) -> None:
        if current is None:
            self.preview_icon.setPixmap(QPixmap())
            self.preview_icon.setText("无图标")
            self.preview_text.setText("没有匹配结果")
            return
        item_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        asset = self.asset_index.items[item_id]
        status_reader = getattr(self.asset_index, "icon_status_text", None)
        status = str(status_reader(item_id) or "") if callable(status_reader) else ""
        path = self.asset_index.cached_icon_for(item_id)
        pixmap = self._pixmap(path, 48) if path else QPixmap()
        if pixmap.isNull():
            self.preview_icon.setPixmap(QPixmap())
            self.preview_icon.setText("准备中…")
            self._queue_ids([item_id], priority=True)
        else:
            self.preview_icon.setText("")
            self.preview_icon.setPixmap(pixmap)
        detail = status or ("图标正在后台准备" if pixmap.isNull() else "可用图标")
        self.preview_text.setText(f"{asset.name}\n{item_id}\n{detail}")
        current.setToolTip(f"{asset.name}\n{item_id}\n{detail}")

    def accept_selection(self) -> None:
        current = self.results.currentItem()
        if current is None:
            return
        self.selected_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
        self.accept()

    def done(self, result: int) -> None:
        self._closing = True
        self._pending_ids.clear()
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(3000)
        super().done(result)


class RegistryPickerDialog(QDialog):
    def __init__(self, title: str, values: dict[str, str], selected_id: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("pickerDialog")
        self.values = dict(values)
        self.selected_id = selected_id
        self.setWindowTitle(title)
        self.resize(650, 500)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setObjectName("pickerSearch")
        self.search.setPlaceholderText("搜索名称或命名空间 ID")
        self.search.textChanged.connect(self.refresh_results)
        layout.addWidget(self.search)
        self.results = QListWidget()
        self.results.setObjectName("pickerResults")
        self.results.itemDoubleClicked.connect(lambda _item: self.accept_selection())
        layout.addWidget(self.results, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        choose = QPushButton("使用此 ID")
        choose.clicked.connect(self.accept_selection)
        buttons.addWidget(cancel)
        buttons.addWidget(choose)
        layout.addLayout(buttons)
        self.refresh_results()

    def refresh_results(self) -> None:
        needle = self.search.text().casefold().strip()
        self.results.clear()
        for identifier, name in sorted(
            self.values.items(), key=lambda value: (str(value[1]).casefold(), value[0]),
        ):
            if needle and needle not in identifier.casefold() and needle not in str(name).casefold():
                continue
            item = QListWidgetItem(
                f"{name}\n{identifier}" if str(name) != identifier else identifier,
            )
            item.setData(Qt.ItemDataRole.UserRole, identifier)
            self.results.addItem(item)
            if identifier == self.selected_id:
                self.results.setCurrentItem(item)
        if self.results.currentItem() is None and self.results.count():
            self.results.setCurrentRow(0)

    def accept_selection(self) -> None:
        current = self.results.currentItem()
        if current is not None:
            self.selected_id = str(current.data(Qt.ItemDataRole.UserRole) or "")
            self.accept()
