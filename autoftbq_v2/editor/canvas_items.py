"""Reusable graphics-view components for the v2 quest editor."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QAbstractScrollArea, QAbstractSpinBox, QComboBox,
    QGraphicsLineItem, QGraphicsPathItem, QGraphicsRectItem, QGraphicsSimpleTextItem,
    QGraphicsView, QListWidget,
)


class QuestCanvas(QGraphicsView):
    view_changed = Signal()
    agent_context_requested = Signal(str)

    MIN_SCENE_MARGIN = 1200.0
    SCENE_MARGIN_VIEWPORTS = 2.0
    EDGE_TRIGGER_RATIO = 0.35

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._panning = False
        self._pan_start = None
        self._rubber_band = False
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def viewport_scene_rect(self) -> QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def reset_scene_bounds(self, content_rect: QRectF | None = None, *, preserve=False) -> None:
        """Reset one chapter to a roomy area that can grow while it is explored."""
        visible = self.viewport_scene_rect()
        content = QRectF(content_rect) if content_rect is not None else self.scene().itemsBoundingRect()
        if content.isEmpty() or not content.isValid():
            content = QRectF(visible.center(), visible.center())
        base = content.united(visible)
        margin_x = max(self.MIN_SCENE_MARGIN, visible.width() * self.SCENE_MARGIN_VIEWPORTS)
        margin_y = max(self.MIN_SCENE_MARGIN, visible.height() * self.SCENE_MARGIN_VIEWPORTS)
        bounds = base.adjusted(-margin_x, -margin_y, margin_x, margin_y)
        if preserve:
            bounds = bounds.united(self.scene().sceneRect())
        self.scene().setSceneRect(bounds)

    def ensure_scene_space(self) -> bool:
        """Extend nearby scene edges without ever shrinking the current chapter."""
        visible = self.viewport_scene_rect()
        bounds = QRectF(self.scene().sceneRect())
        if visible.isEmpty() or bounds.isEmpty():
            self.reset_scene_bounds()
            return True

        trigger_x = max(120.0, visible.width() * self.EDGE_TRIGGER_RATIO)
        trigger_y = max(120.0, visible.height() * self.EDGE_TRIGGER_RATIO)
        growth_x = max(self.MIN_SCENE_MARGIN, visible.width() * self.SCENE_MARGIN_VIEWPORTS)
        growth_y = max(self.MIN_SCENE_MARGIN, visible.height() * self.SCENE_MARGIN_VIEWPORTS)
        changed = False
        if visible.left() <= bounds.left() + trigger_x:
            bounds.setLeft(bounds.left() - growth_x)
            changed = True
        if visible.right() >= bounds.right() - trigger_x:
            bounds.setRight(bounds.right() + growth_x)
            changed = True
        if visible.top() <= bounds.top() + trigger_y:
            bounds.setTop(bounds.top() - growth_y)
            changed = True
        if visible.bottom() >= bounds.bottom() - trigger_y:
            bounds.setBottom(bounds.bottom() + growth_y)
            changed = True
        if changed:
            self.scene().setSceneRect(bounds)
        return changed

    def wheelEvent(self, event):
        current = self.transform().m11()
        factor = 1.16 if event.angleDelta().y() > 0 else 1 / 1.16
        target = current * factor
        if 0.08 <= target <= 6.0:
            self.scale(factor, factor)
            self.view_changed.emit()
        event.accept()

    @staticmethod
    def _interactive_node(item):
        while item is not None:
            if isinstance(item, (QuestNode, ChapterImageNode, QuestLinkNode)):
                return item
            item = item.parentItem()
        return None

    def mousePressEvent(self, event):
        node = self._interactive_node(self.itemAt(event.position().toPoint()))
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
            and isinstance(node, QuestNode)
        ):
            self.agent_context_requested.emit(node.quest.id)
            event.accept()
            return
        blank = node is None
        if event.button() == Qt.MouseButton.LeftButton and blank and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._rubber_band = True
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton and blank:
            self._panning = True
            self._pan_start = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            self.ensure_scene_space()
            current = event.position().toPoint()
            delta = current - self._pan_start
            self._pan_start = current
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self.ensure_scene_space()
            event.accept()
            return
        super().mouseMoveEvent(event)
        self.ensure_scene_space()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.ensure_scene_space()

    def mouseReleaseEvent(self, event):
        if self._rubber_band and event.button() == Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            self._rubber_band = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            return
        if self._panning and event.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self._pan_start = None
            self.viewport().unsetCursor()
            self.view_changed.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class FormWheelNavigationFilter(QObject):
    """Make wheel gestures scroll forms instead of silently changing values."""

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Wheel or not isinstance(watched, (QComboBox, QAbstractSpinBox)):
            return False
        if isinstance(watched, QComboBox) and watched.view().isVisible():
            return False
        parent = watched.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                bar = parent.verticalScrollBar()
                if bar.maximum() > bar.minimum():
                    delta = event.angleDelta().y()
                    step = max(40, bar.singleStep() * 3)
                    bar.setValue(bar.value() - step if delta > 0 else bar.value() + step)
                    return True
            parent = parent.parentWidget()
        return True


def apply_light_palette(app: QApplication) -> None:
    """Keep native and dynamically-created controls readable on dark desktops."""

    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f3f1eb",
        QPalette.ColorRole.WindowText: "#202722",
        QPalette.ColorRole.Base: "#fffefb",
        QPalette.ColorRole.AlternateBase: "#f0ede5",
        QPalette.ColorRole.ToolTipBase: "#fffefb",
        QPalette.ColorRole.ToolTipText: "#202722",
        QPalette.ColorRole.Text: "#202722",
        QPalette.ColorRole.Button: "#faf8f2",
        QPalette.ColorRole.ButtonText: "#303730",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: "#d4e8df",
        QPalette.ColorRole.HighlightedText: "#164f40",
        QPalette.ColorRole.PlaceholderText: "#657169",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)


class QuestNode(QGraphicsRectItem):
    WIDTH = 168
    HEIGHT = 70

    def __init__(
        self, quest, x: float, y: float, icon_path: str = "", on_move=None,
        agent_context=False, icon_id: str = "", icon_loader=None,
        icon_placeholder: str = "", icon_status: str = "",
    ):
        super().__init__(0, 0, self.WIDTH, self.HEIGHT)
        self.quest = quest
        self.on_move = on_move
        self.agent_context = bool(agent_context)
        self.icon_id = str(icon_id or "")
        self.icon_loader = icon_loader
        self.icon_item = None
        self.icon_placeholder_item = None
        self.icon_status = str(icon_status or "")
        self.edges = []
        self.setData(0, quest.id)
        self.setPos(x, y)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        task_type = quest.tasks[0].type if quest.tasks else "checkmark"
        colors = {
            "item": "#d9efe9",
            "kill": "#f5ded5",
            "dimension": "#dce8f4",
            "advancement": "#f3e7c5",
        }
        self.setBrush(QBrush(QColor(colors.get(task_type, "#eee9df"))))
        self._update_border(False)
        title = quest.title
        target = quest.tasks[0].target if quest.tasks else ""
        text_x = 14
        shape = quest.shape or "circle"
        if shape != "none":
            marker = QGraphicsPathItem(self.shape_path(shape), self)
            marker.setPos(9, 17)
            marker.setPen(QPen(QColor("#65756d"), 1.5))
            marker.setBrush(QBrush(QColor("#f8f6ef")))
            marker.setZValue(1)
            self.shape_item = marker
            text_x = 52
        if self.icon_id:
            text_x = 52
            if icon_placeholder:
                placeholder = QGraphicsSimpleTextItem(str(icon_placeholder), self)
                font = QFont()
                font.setPointSize(14)
                font.setBold(True)
                placeholder.setFont(font)
                placeholder.setBrush(QBrush(QColor("#78817c")))
                bounds = placeholder.boundingRect()
                placeholder.setPos(28 - bounds.width() / 2, 36 - bounds.height() / 2)
                placeholder.setZValue(2)
                self.icon_placeholder_item = placeholder
        self.set_icon_path(icon_path)
        text_width = self.WIDTH - text_x - 9
        self.title_item = self.scene_text(title, 11, True, QPointF(text_x, 10), text_width)
        self.detail_item = self.scene_text(target or task_type, 8, False, QPointF(text_x, 39), text_width)
        self._update_tooltip(target or task_type)

    def set_icon_path(self, icon_path: str) -> bool:
        if not icon_path:
            return False
        pixmap = self.icon_loader(icon_path, 34) if self.icon_loader else QPixmap(icon_path)
        if pixmap.isNull():
            return False
        if not self.icon_loader:
            pixmap = pixmap.scaled(
                34, 34, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        if self.icon_item is None:
            from PySide6.QtWidgets import QGraphicsPixmapItem

            self.icon_item = QGraphicsPixmapItem(pixmap, self)
            self.icon_item.setPos(11, 19)
            self.icon_item.setZValue(2)
        else:
            self.icon_item.setPixmap(pixmap)
        if self.icon_placeholder_item is not None:
            self.icon_placeholder_item.hide()
        return True

    def _update_tooltip(self, detail: str | None = None) -> None:
        detail = detail if detail is not None else (self.quest.tasks[0].target if self.quest.tasks else "")
        context = "\n已加入 Agent 上下文" if self.agent_context else "\nAlt + 左键：加入 Agent 上下文"
        icon_detail = f"\n图标：{self.icon_status}" if self.icon_status else ""
        self.setToolTip(f"{self.quest.title}\n{detail}\nID: {self.quest.id}{icon_detail}{context}")

    def _update_border(self, selected: bool) -> None:
        if self.agent_context:
            color = QColor("#8dac20" if not selected else "#527000")
            self.setPen(QPen(color, 3.2 if selected else 2.8, Qt.PenStyle.DashLine))
        else:
            self.setPen(QPen(QColor("#19715a") if selected else QColor("#a9a398"), 2.2 if selected else 1.4))

    def set_agent_context(self, enabled: bool) -> None:
        self.agent_context = bool(enabled)
        self._update_border(self.isSelected())
        self._update_tooltip()

    @staticmethod
    def shape_path(shape: str):
        path = QPainterPath()
        bounds = QRectF(0, 0, 34, 34)
        if shape == "square":
            path.addRect(bounds)
        elif shape == "rsquare":
            path.addRoundedRect(bounds, 7, 7)
        elif shape == "diamond":
            path.moveTo(17, 0)
            path.lineTo(34, 17)
            path.lineTo(17, 34)
            path.lineTo(0, 17)
            path.closeSubpath()
        elif shape in {"pentagon", "hexagon", "octagon", "gear"}:
            sides = {"pentagon": 5, "hexagon": 6, "octagon": 8, "gear": 16}[shape]
            for index in range(sides):
                radius = 17 if shape != "gear" or index % 2 == 0 else 12
                angle = -math.pi / 2 + index * math.tau / sides
                point = QPointF(17 + math.cos(angle) * radius, 17 + math.sin(angle) * radius)
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            path.closeSubpath()
        elif shape == "heart":
            path.moveTo(17, 32)
            path.cubicTo(14, 27, 2, 20, 2, 11)
            path.cubicTo(2, 2, 13, 0, 17, 8)
            path.cubicTo(21, 0, 32, 2, 32, 11)
            path.cubicTo(32, 20, 20, 27, 17, 32)
            path.closeSubpath()
        else:
            path.addEllipse(bounds)
        return path

    def scene_text(self, text, size, bold, pos, max_width):
        from PySide6.QtWidgets import QGraphicsSimpleTextItem

        font = QFont("Microsoft YaHei UI", size, QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
        visible_text = QFontMetrics(font).elidedText(str(text), Qt.TextElideMode.ElideRight, int(max_width))
        item = QGraphicsSimpleTextItem(visible_text, self)
        item.setFont(font)
        item.setBrush(QBrush(QColor("#242824" if bold else "#667069")))
        item.setPos(pos)
        return item

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.GraphicsItemChange.ItemSelectedChange:
            self._update_border(bool(value))
        elif change == QGraphicsRectItem.GraphicsItemChange.ItemPositionHasChanged:
            for edge in self.edges:
                edge.update_position()
        return super().itemChange(change, value)

    def add_edge(self, edge):
        self.edges.append(edge)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.on_move:
            self.on_move(self.quest.id, self.pos())


class AgentContextChapterList(QListWidget):
    agent_context_requested = Signal(str)

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                self.agent_context_requested.emit(str(item.data(Qt.ItemDataRole.UserRole) or ""))
                event.accept()
                return
        super().mousePressEvent(event)


class ChapterImageNode(QGraphicsRectItem):
    """Movable representation of an FTB Quests chapter image."""

    def __init__(self, raw: dict, image_path: str = "", on_move=None):
        width = max(18.0, abs(float(raw.get("width", 1.0) or 1.0)) * 72)
        height = max(18.0, abs(float(raw.get("height", 1.0) or 1.0)) * 72)
        super().__init__(0, 0, width, height)
        self.raw = raw
        self.object_id = str(raw.get("id") or "")
        self.on_move = on_move
        self.setData(1, "chapter_image")
        self.setData(2, self.object_id)
        self.setPos(float(raw.get("x", 0.0) or 0.0) * 72, float(raw.get("y", 0.0) or 0.0) * 72)
        self.setRotation(float(raw.get("rotation", 0.0) or 0.0))
        self.setZValue(float(raw.get("order", -2) or -2))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable,
            not bool(raw.get("position_locked", False)),
        )
        self.setPen(QPen(QColor("#789184"), 1.2, Qt.PenStyle.DashLine))
        self.setBrush(QBrush(QColor(218, 230, 222, 80)))
        if image_path:
            from PySide6.QtWidgets import QGraphicsPixmapItem

            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                rendered = pixmap.scaled(
                    int(width), int(height), Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.pixmap_item = QGraphicsPixmapItem(rendered, self)
                self.pixmap_item.setOpacity(max(0.0, min(1.0, float(raw.get("alpha", 255) or 0) / 255)))
        self.setToolTip(f"章节图片：{raw.get('image', '')}\nID: {self.object_id}")

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.on_move:
            self.on_move(self.object_id, self.pos())


class QuestLinkNode(QGraphicsRectItem):
    WIDTH = 150
    HEIGHT = 58

    def __init__(self, raw: dict, target_title: str, on_move=None, on_open=None):
        super().__init__(0, 0, self.WIDTH, self.HEIGHT)
        self.raw = raw
        self.object_id = str(raw.get("id") or "")
        self.linked_quest = str(raw.get("linked_quest") or "")
        self.on_move = on_move
        self.on_open = on_open
        self.setData(1, "quest_link")
        self.setData(2, self.object_id)
        self.setPos(float(raw.get("x", 0.0) or 0.0) * 72, float(raw.get("y", 0.0) or 0.0) * 72)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setBrush(QBrush(QColor("#e2ece8")))
        self.setPen(QPen(QColor("#19715a"), 1.6, Qt.PenStyle.DashLine))
        title = target_title or "目标任务不存在"
        label = QuestNode.scene_text(self, f"跳转：{title}", 9, True, QPointF(10, 8), self.WIDTH - 20)
        label.setBrush(QBrush(QColor("#164f42")))
        QuestNode.scene_text(self, self.linked_quest or "尚未选择目标", 7, False, QPointF(10, 32), self.WIDTH - 20)
        self.setToolTip(f"双击定位目标任务\n{title}\nID: {self.linked_quest}")

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.on_move:
            self.on_move(self.object_id, self.pos())

    def mouseDoubleClickEvent(self, event):
        if self.on_open and self.linked_quest:
            self.on_open(self.linked_quest)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class DependencyLine(QGraphicsLineItem):
    def __init__(self, source: QuestNode, target: QuestNode):
        super().__init__()
        self.source = source
        self.target = target
        self.setPen(QPen(QColor("#8a958e"), 2))
        self.setZValue(-1)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setToolTip(f"{source.quest.title} -> {target.quest.title}")
        source.add_edge(self)
        target.add_edge(self)
        self.update_position()

    def update_position(self):
        start = self.source.sceneBoundingRect().center()
        end = self.target.sceneBoundingRect().center()
        self.setLine(start.x(), start.y(), end.x(), end.y())


class CurvedDependencyLine(QGraphicsPathItem):
    def __init__(self, source: QuestNode, target: QuestNode, controls: list[float]):
        super().__init__()
        self.source = source
        self.target = target
        self.controls = controls
        self.setPen(QPen(QColor("#8a958e"), 2))
        self.setZValue(-1)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setToolTip(f"{source.quest.title} -> {target.quest.title}（曲线）")
        source.add_edge(self)
        target.add_edge(self)
        self.update_position()

    def update_position(self):
        start = self.source.sceneBoundingRect().center()
        end = self.target.sceneBoundingRect().center()
        path = QPainterPath(start)
        path.cubicTo(
            QPointF(float(self.controls[0]) * 72, float(self.controls[1]) * 72),
            QPointF(float(self.controls[2]) * 72, float(self.controls[3]) * 72),
            end,
        )
        self.setPath(path)
