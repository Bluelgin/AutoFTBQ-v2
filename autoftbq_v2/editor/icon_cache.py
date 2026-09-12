"""Bounded GUI-thread pixmap cache for quest icons."""

from __future__ import annotations

from collections import OrderedDict
import os
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


class IconPixmapCache:
    def __init__(self, max_entries: int = 256, ttl_seconds: int = 600):
        self.max_entries = max(16, int(max_entries))
        self.ttl_seconds = max(30, int(ttl_seconds))
        self._entries: OrderedDict[tuple, tuple[float, QPixmap]] = OrderedDict()

    def get(self, path: str, size: int = 34) -> QPixmap:
        if not path or not os.path.isfile(path):
            return QPixmap()
        try:
            modified = os.path.getmtime(path)
        except OSError:
            return QPixmap()
        key = (os.path.abspath(path), int(size), modified)
        now = time.monotonic()
        cached = self._entries.pop(key, None)
        if cached is not None and now - cached[0] <= self.ttl_seconds:
            self._entries[key] = (now, cached[1])
            return cached[1]
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return pixmap
        scaled = pixmap.scaled(
            int(size), int(size), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._entries[key] = (now, scaled)
        self.cleanup(now)
        return scaled

    def cleanup(self, now: float | None = None) -> int:
        current = time.monotonic() if now is None else float(now)
        stale = [
            key for key, (used_at, _pixmap) in self._entries.items()
            if current - used_at > self.ttl_seconds or not os.path.isfile(key[0])
        ]
        for key in stale:
            self._entries.pop(key, None)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return len(stale)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
