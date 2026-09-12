"""Small offline renderer for the static subset of Minecraft item models."""

from __future__ import annotations

import hashlib

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF, QTransform


def _first_animation_frame(image: QImage) -> QImage:
    if image.isNull():
        return QImage()
    width = image.width()
    if width > 0 and image.height() > width and image.height() % width == 0:
        return image.copy(QRect(0, 0, width, width))
    return image


def _draw_mapped(painter: QPainter, image: QImage, target: QPolygonF) -> None:
    image = _first_animation_frame(image)
    if image.isNull():
        return
    source = QPolygonF([
        QPointF(0, 0),
        QPointF(image.width(), 0),
        QPointF(image.width(), image.height()),
        QPointF(0, image.height()),
    ])
    transform = QTransform.quadToQuad(source, target)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    painter.setTransform(transform, combine=True)
    painter.drawImage(QPointF(0, 0), image)
    painter.restore()


def _render_layers(images: list[QImage], size: int) -> QImage:
    output = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    margin = max(2, size // 16)
    target = QRect(margin, margin, size - margin * 2, size - margin * 2)
    for image in images:
        frame = _first_animation_frame(image)
        if not frame.isNull():
            painter.drawImage(target, frame)
    painter.end()
    return output


def _texture(images: dict[str, QImage], *names: str) -> QImage:
    for name in names:
        image = images.get(name)
        if image is not None and not image.isNull():
            return image
    return next((image for image in images.values() if not image.isNull()), QImage())


def _render_cube(images: dict[str, QImage], size: int) -> QImage:
    output = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    scale = size / 64.0
    top_poly = QPolygonF([
        QPointF(32 * scale, 4 * scale), QPointF(58 * scale, 17 * scale),
        QPointF(32 * scale, 30 * scale), QPointF(6 * scale, 17 * scale),
    ])
    left_poly = QPolygonF([
        QPointF(6 * scale, 17 * scale), QPointF(32 * scale, 30 * scale),
        QPointF(32 * scale, 58 * scale), QPointF(6 * scale, 45 * scale),
    ])
    right_poly = QPolygonF([
        QPointF(32 * scale, 30 * scale), QPointF(58 * scale, 17 * scale),
        QPointF(58 * scale, 45 * scale), QPointF(32 * scale, 58 * scale),
    ])

    _draw_mapped(painter, _texture(images, "up", "top", "end", "all", "particle"), top_poly)
    _draw_mapped(painter, _texture(images, "north", "west", "side", "all", "particle"), left_poly)
    painter.setBrush(QColor(0, 0, 0, 32))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPolygon(left_poly)
    _draw_mapped(painter, _texture(images, "south", "east", "side", "all", "particle"), right_poly)
    painter.setBrush(QColor(0, 0, 0, 58))
    painter.drawPolygon(right_poly)
    painter.end()
    return output


def classify_static_model(model: dict, texture_names) -> str:
    names = tuple(str(name) for name in texture_names)
    parent = str(model.get("parent") or "")
    if model.get("loader") or parent.startswith("builtin/"):
        return "dynamic"
    if sum(name.startswith("layer") for name in names) > 1:
        return "layered"
    if isinstance(model.get("elements"), list) or any(
        name in names for name in ("all", "side", "up", "down", "north", "south", "east", "west")
    ):
        return "block"
    return "texture"


def render_static_model(model: dict, images: dict[str, QImage], size: int = 64) -> tuple[QImage, str]:
    """Render a model and return ``(image, kind)``; null means unsupported."""
    if not images:
        return QImage(), "unavailable"

    kind = classify_static_model(model, images)
    parent = str(model.get("parent") or "")
    if kind == "dynamic":
        return QImage(), "dynamic"

    layers = [images[key] for key in sorted(images) if key.startswith("layer")]
    if layers or parent.endswith(("item/generated", "item/handheld", "item/handheld_rod")):
        return _render_layers(layers or list(images.values()), size), kind

    if kind == "block":
        return _render_cube(images, size), "block"

    return QImage(), "texture"


def render_spawn_egg_placeholder(item_id: str, size: int = 64) -> QImage:
    """Create a deterministic representative icon when Minecraft supplies colors at runtime."""
    digest = hashlib.sha1(str(item_id).encode("utf-8")).digest()
    base = QColor(64 + digest[0] % 128, 64 + digest[1] % 128, 64 + digest[2] % 128)
    accent = QColor(96 + digest[3] % 144, 96 + digest[4] % 144, 96 + digest[5] % 144)
    output = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(base)
    painter.drawEllipse(QRect(size // 5, size // 10, size * 3 // 5, size * 4 // 5))
    painter.setBrush(accent)
    spots = (
        (digest[6] % 8 + 4, digest[7] % 9 + 3),
        (digest[8] % 8 + 4, digest[9] % 9 + 3),
        (digest[10] % 8 + 4, digest[11] % 9 + 3),
        (digest[12] % 8 + 4, digest[13] % 9 + 3),
    )
    scale = size / 16.0
    for x, y in spots:
        painter.drawRect(QRect(round(x * scale), round(y * scale), max(2, round(2 * scale)), max(2, round(2 * scale))))
    painter.end()
    return output
