"""First-run AI configuration shared by the v2 workspace."""

from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlsplit

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ai_clients import create_chat_client
from ai_providers import CUSTOM_PROVIDER, PROVIDER_PRESETS, normalize_provider, resolve_provider_model
from .app_logging import LOGGER_NAME


LOGGER = logging.getLogger(LOGGER_NAME)


def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def validate_ai_config(config: dict) -> str:
    engine = str(config.get("engine") or "generic")
    if engine == "ollama":
        return "" if str(config.get("ollama_model") or "").strip() else "请填写 Ollama 模型名称"

    provider = normalize_provider(config.get("provider"))
    api_key = str(config.get("api_key") or "").strip()
    model = resolve_provider_model(provider, config.get("api_model"))
    if provider != CUSTOM_PROVIDER and not api_key:
        return "请填写 API Key"
    if provider == CUSTOM_PROVIDER:
        api_url = str(config.get("api_url") or "").strip()
        parsed = urlsplit(api_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return "请填写有效的 HTTP(S) API 地址"
    if not model:
        return "请填写模型 ID"
    return ""


def client_from_config(config: dict):
    error = validate_ai_config(config)
    if error:
        raise ValueError(error)
    engine = str(config.get("engine") or "generic")
    provider = normalize_provider(config.get("provider"))
    return create_chat_client(
        "ollama" if engine == "ollama" else "generic",
        api_key=config.get("api_key", ""),
        ollama_model=config.get("ollama_model"),
        provider=provider,
        api_url=config.get("api_url") if provider == CUSTOM_PROVIDER else None,
        api_model=config.get("api_model"),
    )


def save_config(path: str, ai_config: dict) -> None:
    config = load_config(path)
    config.update(ai_config)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=4)
        handle.write("\n")
    os.replace(temporary, path)


class AIConnectionTestThread(QThread):
    completed = Signal(bool, str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = dict(config)

    def run(self) -> None:
        try:
            client = client_from_config(self.config)
            result = client.chat(
                [{"role": "user", "content": "Reply with OK only. Do not explain."}],
                temperature=0,
                max_tokens=512,
            )
            content = result[0] if isinstance(result, tuple) else result
            if not str(content or "").strip():
                raise RuntimeError("模型返回了空内容")
            self.completed.emit(True, "连接成功，可以保存并使用 Agent")
        except Exception as exc:
            LOGGER.exception("AI connection test failed")
            self.completed.emit(False, str(exc) or type(exc).__name__)


class AISetupDialog(QDialog):
    def __init__(self, config_path: str, required: bool = False, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.required = required
        self.test_thread = None
        self.tested_signature = ""
        self.setWindowTitle("配置 AI")
        self.setObjectName("aiSetupDialog")
        self.setMinimumWidth(560)
        self.setStyleSheet("""
            QDialog#aiSetupDialog { background: #f3f1eb; color: #202722; }
            QDialog#aiSetupDialog QLabel { color: #303a34; background: transparent; }
            QDialog#aiSetupDialog #agentTitle { color: #202a24; font-size: 18px; font-weight: 800; }
            QDialog#aiSetupDialog #mainMuted { color: #59645d; font-size: 10px; }
            QDialog#aiSetupDialog #fieldHelp {
                color: #315a4c; background: #e5eee9; border: 1px solid #cbdcd3;
                border-radius: 7px; padding: 8px;
            }
            QDialog#aiSetupDialog QLineEdit, QDialog#aiSetupDialog QComboBox {
                background: #fffefb; color: #202722; border: 1px solid #cfc9bd;
                border-radius: 8px; min-height: 26px; padding: 5px 9px;
            }
            QDialog#aiSetupDialog QLineEdit:disabled, QDialog#aiSetupDialog QComboBox:disabled {
                background: #e8e5dd; color: #626c66; border-color: #d0cbc1;
            }
            QDialog#aiSetupDialog QComboBox QAbstractItemView {
                background: #fffefb; color: #202722; selection-background-color: #d4e8df;
                selection-color: #164f40;
            }
            QDialog#aiSetupDialog QPushButton {
                background: #faf8f2; color: #303730; border: 1px solid #d3cec3;
                border-radius: 8px; padding: 7px 12px;
            }
            QDialog#aiSetupDialog QPushButton:hover { background: #fffefb; border-color: #778f82; }
            QDialog#aiSetupDialog #agentButton {
                background: #d7f05c; color: #1c251f; border: none; font-weight: 800;
            }
            QDialog#aiSetupDialog #agentButton:disabled {
                background: #d9d9ca; color: #68706b; border: 1px solid #c8c8ba;
            }
        """)

        layout = QVBoxLayout(self)
        title = QLabel("先连接你的 AI")
        title.setObjectName("agentTitle")
        layout.addWidget(title)
        intro = QLabel("Agent 只有在连接测试成功后才会启用。配置保存在本机，不会写入任务书或行动记录。")
        intro.setWordWrap(True)
        intro.setObjectName("mainMuted")
        layout.addWidget(intro)

        form = QFormLayout()
        self.engine = QComboBox()
        self.engine.addItem("云端 / OpenAI 兼容 API", "generic")
        self.engine.addItem("Ollama 本地模型", "ollama")
        self.provider = QComboBox()
        for name in PROVIDER_PRESETS:
            self.provider.addItem(name, name)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("API Key（自定义本地服务可留空）")
        self.api_url = QLineEdit()
        self.api_url.setPlaceholderText("例如：https://example.com/v1/chat/completions")
        self.model = QLineEdit()
        self.model.setPlaceholderText("模型 ID")
        self.ollama_model = QLineEdit()
        self.ollama_model.setPlaceholderText("例如：qwen3:8b")
        form.addRow("接入方式", self.engine)
        form.addRow("服务商", self.provider)
        form.addRow("API Key", self.api_key)
        form.addRow("API 地址", self.api_url)
        form.addRow("模型 ID", self.model)
        form.addRow("Ollama 模型", self.ollama_model)
        layout.addLayout(form)

        self.state = QLabel("修改配置后请测试连接")
        self.state.setWordWrap(True)
        self.state.setObjectName("fieldHelp")
        layout.addWidget(self.state)
        buttons = QHBoxLayout()
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self.test_connection)
        self.cancel_button = QPushButton("稍后，仅使用离线编辑" if required else "取消")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("保存并启用 Agent")
        self.save_button.setObjectName("agentButton")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_and_accept)
        buttons.addWidget(self.test_button)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self._load_existing()
        self.engine.currentIndexChanged.connect(self._engine_changed)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        for widget in (self.api_key, self.api_url, self.model, self.ollama_model):
            widget.textChanged.connect(self._invalidate_test)
        self._engine_changed()
        self.api_url.setEnabled(
            self.provider.currentData() == CUSTOM_PROVIDER and self.engine.currentData() != "ollama"
        )

    def _load_existing(self) -> None:
        config = load_config(self.config_path)
        engine = "ollama" if config.get("engine") == "ollama" else "generic"
        self.engine.setCurrentIndex(max(0, self.engine.findData(engine)))
        provider = normalize_provider(config.get("provider"))
        self.provider.setCurrentIndex(max(0, self.provider.findData(provider)))
        self.api_key.setText(str(config.get("api_key") or ""))
        self.api_url.setText(str(config.get("api_url") or ""))
        self.model.setText(resolve_provider_model(provider, config.get("api_model")))
        self.ollama_model.setText(str(config.get("ollama_model") or "qwen2.5-coder:7b"))

    def _signature(self) -> str:
        safe = dict(self.values())
        return json.dumps(safe, sort_keys=True, ensure_ascii=False)

    def values(self) -> dict:
        return {
            "engine": str(self.engine.currentData()),
            "provider": str(self.provider.currentData()),
            "api_key": self.api_key.text().strip(),
            "api_url": self.api_url.text().strip(),
            "api_model": self.model.text().strip(),
            "ollama_model": self.ollama_model.text().strip(),
        }

    def _invalidate_test(self, *_args) -> None:
        self.tested_signature = ""
        self.save_button.setEnabled(False)
        self.state.setText("配置已变化，请重新测试连接")

    def _engine_changed(self, *_args) -> None:
        local = self.engine.currentData() == "ollama"
        for widget in (self.provider, self.api_key, self.api_url, self.model):
            widget.setEnabled(not local)
        self.ollama_model.setEnabled(local)
        self._invalidate_test()

    def _provider_changed(self, *_args) -> None:
        provider = str(self.provider.currentData())
        preset = PROVIDER_PRESETS.get(provider, {})
        custom = provider == CUSTOM_PROVIDER
        self.api_url.setEnabled(custom and self.engine.currentData() != "ollama")
        if not custom:
            self.api_url.setText(str(preset.get("chat_url") or ""))
            self.model.setText(str(preset.get("model") or ""))
        self._invalidate_test()

    def test_connection(self) -> None:
        config = self.values()
        error = validate_ai_config(config)
        if error:
            self.state.setText(error)
            return
        self.test_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.state.setText("正在测试连接，请稍候…")
        self.test_thread = AIConnectionTestThread(config, self)
        self.test_thread.completed.connect(self._test_finished)
        self.test_thread.finished.connect(self.test_thread.deleteLater)
        self.test_thread.start()

    def _test_finished(self, success: bool, message: str) -> None:
        self.test_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.state.setText(message)
        self.tested_signature = self._signature() if success else ""
        self.save_button.setEnabled(success)
        self.test_thread = None

    def reject(self) -> None:
        if self.test_thread is not None and self.test_thread.isRunning():
            self.state.setText("连接测试仍在进行，请等待测试完成")
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self.test_thread is not None and self.test_thread.isRunning():
            self.state.setText("连接测试仍在进行，请等待测试完成")
            event.ignore()
            return
        super().closeEvent(event)

    def save_and_accept(self) -> None:
        if self.tested_signature != self._signature():
            QMessageBox.warning(self, "需要重新测试", "配置已经变化，请重新测试连接。")
            return
        try:
            save_config(self.config_path, self.values())
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.accept()
