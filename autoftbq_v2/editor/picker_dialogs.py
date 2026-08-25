"""Searchable item and registry picker dialogs."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)

from ..infrastructure.asset_index import AssetIndex


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
