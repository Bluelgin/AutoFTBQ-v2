"""Qt worker adapters for long-running application services."""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QThread, Signal

from .app_logging import LOGGER_NAME
from .modpack_scan import ModpackScanService


LOGGER = logging.getLogger(LOGGER_NAME)


class AgentWorker(QThread):
    answered = Signal(str)
    failed = Signal(str)
    action = Signal(str, str)

    def __init__(self, agent, prompt: str):
        super().__init__()
        self.agent = agent
        self.prompt = prompt

    def run(self):
        self.agent.on_action = self._on_action
        try:
            self.answered.emit(self.agent.run(self.prompt))
        except Exception as exc:
            LOGGER.exception("Agent run failed")
            self.failed.emit(str(exc) or type(exc).__name__)

    def _on_action(self, name, arguments, result):
        detail_value = result if str(name).startswith("agent_") else arguments
        detail = json.dumps(detail_value, ensure_ascii=False)
        LOGGER.info("Agent tool: %s %s", name, detail[:1200])
        self.action.emit(name, detail)


class ModpackScanWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, folder: str, cache_root: str, parent=None, load_quest_book: bool = True):
        super().__init__(parent)
        self.folder = folder
        self.cache_root = cache_root
        self.load_quest_book = load_quest_book

    def run(self):
        try:
            result = ModpackScanService(self.cache_root).scan(
                self.folder,
                load_quest_book=self.load_quest_book,
                progress=self.progress.emit,
                cancelled=self.isInterruptionRequested,
            )
            self.completed.emit(result)
        except InterruptedError:
            self.cancelled.emit()
        except Exception as exc:
            LOGGER.exception("Modpack scan failed for %s", self.folder)
            self.failed.emit(str(exc) or type(exc).__name__)


class IconPrewarmWorker(QThread):
    icon_ready = Signal(str, str)
    completed = Signal(int)

    def __init__(self, asset_index, item_ids=(), image_ids=(), parent=None):
        super().__init__(parent)
        self.asset_index = asset_index
        self.item_ids = list(dict.fromkeys(str(value) for value in item_ids if value))
        self.image_ids = list(dict.fromkeys(str(value) for value in image_ids if value))

    def run(self):
        count = 0
        for item_id in self.item_ids:
            if self.isInterruptionRequested():
                break
            try:
                path = self.asset_index.icon_for(item_id)
            except Exception:
                LOGGER.exception("Icon prewarm failed for %s", item_id)
                continue
            if path:
                count += 1
                self.icon_ready.emit(item_id, path)
        for image_id in self.image_ids:
            if self.isInterruptionRequested():
                break
            try:
                if self.asset_index.image_for(image_id):
                    count += 1
            except Exception:
                LOGGER.exception("Chapter image prewarm failed for %s", image_id)
        self.completed.emit(count)


class CacheCleanupWorker(QThread):
    completed = Signal(object)

    def __init__(self, asset_index, parent=None):
        super().__init__(parent)
        self.asset_index = asset_index

    def run(self):
        try:
            self.completed.emit(self.asset_index.cleanup_cache())
        except Exception:
            LOGGER.exception("Icon cache cleanup failed")
            self.completed.emit({"removed": 0, "bytes_removed": 0, "remaining_bytes": 0})
