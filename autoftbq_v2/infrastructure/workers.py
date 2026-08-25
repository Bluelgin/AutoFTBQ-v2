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
            )
            self.completed.emit(result)
        except Exception as exc:
            LOGGER.exception("Modpack scan failed for %s", self.folder)
            self.failed.emit(str(exc) or type(exc).__name__)
