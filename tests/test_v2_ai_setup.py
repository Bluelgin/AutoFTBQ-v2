import json
import os
import tempfile
import unittest
from unittest.mock import Mock
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from autoftbq_v2.infrastructure.ai_setup import (
    AIConnectionTestThread,
    AISetupDialog,
    client_from_config,
    load_config,
    save_config,
    validate_ai_config,
)
from autoftbq_v2.ui import MainWindow


class V2AISetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_validation_supports_presets_custom_and_ollama(self):
        self.assertIn("API Key", validate_ai_config({"engine": "generic", "provider": "DeepSeek"}))
        self.assertEqual(validate_ai_config({
            "engine": "generic",
            "provider": "第三方自定义",
            "api_url": "http://127.0.0.1:1234/v1/chat/completions",
            "api_model": "local-model",
        }), "")
        self.assertEqual(validate_ai_config({
            "engine": "ollama",
            "ollama_model": "qwen3:8b",
        }), "")

    def test_custom_config_builds_existing_compatible_client(self):
        client = client_from_config({
            "engine": "generic",
            "provider": "第三方自定义",
            "api_url": "http://localhost:1234/v1/chat/completions",
            "api_model": "custom-model",
        })
        self.assertEqual(client.api_url, "http://localhost:1234/v1/chat/completions")
        self.assertEqual(client.model, "custom-model")

    def test_atomic_save_preserves_non_ai_settings(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "config.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"density": "rich", "mod_folder": "pack"}, handle)

            save_config(path, {
                "engine": "ollama",
                "ollama_model": "qwen3:8b",
            })

            saved = load_config(path)
            self.assertEqual(saved["density"], "rich")
            self.assertEqual(saved["mod_folder"], "pack")
            self.assertEqual(saved["ollama_model"], "qwen3:8b")
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_dialog_requires_successful_test_before_save(self):
        with tempfile.TemporaryDirectory() as root:
            dialog = AISetupDialog(os.path.join(root, "config.json"))
            dialog.engine.setCurrentIndex(dialog.engine.findData("ollama"))
            dialog.ollama_model.setText("qwen3:8b")
            self.assertFalse(dialog.save_button.isEnabled())

            dialog._test_finished(True, "连接成功")
            self.assertTrue(dialog.save_button.isEnabled())
            dialog.ollama_model.setText("another-model")
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.close()

    def test_connection_test_leaves_room_for_reasoning_models(self):
        client = Mock()
        client.chat.return_value = ("OK", False)
        completed = []
        thread = AIConnectionTestThread({"engine": "ollama", "ollama_model": "test"})
        thread.completed.connect(lambda success, message: completed.append((success, message)))

        with patch("autoftbq_v2.infrastructure.ai_setup.client_from_config", return_value=client):
            thread.run()

        self.assertEqual(client.chat.call_args.kwargs["max_tokens"], 512)
        self.assertEqual(completed[0][0], True)

    def test_ai_dialog_has_explicit_readable_palette(self):
        with tempfile.TemporaryDirectory() as root:
            dialog = AISetupDialog(os.path.join(root, "config.json"))
            style = dialog.styleSheet().casefold()

            self.assertEqual(dialog.objectName(), "aiSetupDialog")
            self.assertIn("background: #f3f1eb", style)
            self.assertIn("color: #303a34", style)
            self.assertIn("qlineedit", style)
            dialog.close()

    def test_workspace_locks_only_agent_when_config_is_missing(self):
        with tempfile.TemporaryDirectory() as root:
            window = MainWindow()
            window.ai_config_path = os.path.join(root, "missing.json")

            self.assertFalse(window.refresh_ai_state())
            self.assertFalse(window.prompt.isEnabled())
            self.assertFalse(window.send_button.isEnabled())
            self.assertTrue(window.editor_panel.isEnabled())
            window.open_ai_setup = Mock(return_value=False)
            window.ensure_ai_setup()
            window.open_ai_setup.assert_called_once_with(required=True)
            window.close()


if __name__ == "__main__":
    unittest.main()
