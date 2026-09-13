import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from autoftbq_v2.ux_polish import PolishedMainWindow, SimplifiedAISetupDialog


class V2UxPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings = QSettings("AutoFTBQ", "Studio")
        self.settings.clear()
        self.settings.sync()

    def tearDown(self):
        self.settings.clear()
        self.settings.sync()

    def test_first_run_opens_welcome_page(self):
        with tempfile.TemporaryDirectory() as root:
            window = PolishedMainWindow(restore_workspace=False, workspace_dir=root)
            self.addCleanup(window.close)
            self.assertIs(window.workspace_modes.currentWidget(), window.welcome_page)
            self.assertFalse(window.continue_button.isEnabled())
            self.assertIn("首页", window.windowTitle())

    def test_basic_mode_hides_advanced_editor_tabs(self):
        with tempfile.TemporaryDirectory() as root:
            window = PolishedMainWindow(restore_workspace=False, workspace_dir=root)
            self.addCleanup(window.close)
            expert = window.editor_tabs.indexOf(window.expert_tabs)
            book = next(i for i in range(window.editor_tabs.count()) if window.editor_tabs.tabText(i) == "任务书")
            display = next(i for i in range(window.task_tabs.count()) if window.task_tabs.tabText(i) == "显示与推进")
            self.assertEqual(window.editor_tabs.tabText(expert), "检查")
            self.assertTrue(window.editor_tabs.isTabVisible(expert))
            self.assertFalse(window.expert_tabs.isTabVisible(0))
            self.assertFalse(window.editor_tabs.isTabVisible(book))
            self.assertFalse(window.task_tabs.isTabVisible(display))
            window.set_advanced_mode(True)
            self.assertEqual(window.editor_tabs.tabText(expert), "专家")
            self.assertTrue(window.expert_tabs.isTabVisible(0))
            self.assertTrue(window.editor_tabs.isTabVisible(book))
            self.assertTrue(window.task_tabs.isTabVisible(display))

    def test_canvas_toolbar_exposes_more_menu_and_context_hint(self):
        with tempfile.TemporaryDirectory() as root:
            window = PolishedMainWindow(restore_workspace=False, workspace_dir=root)
            self.addCleanup(window.close)
            self.assertEqual(window.more_tools_button.text(), "更多 ▾")
            self.assertIsNotNone(window.more_tools_button.menu())
            self.assertIn("右键任务", window.agent_context_label.text())

    def test_run_marker_is_removed_on_clean_close(self):
        with tempfile.TemporaryDirectory() as root:
            window = PolishedMainWindow(restore_workspace=False, workspace_dir=root)
            marker = window._run_marker_path
            self.assertTrue(os.path.exists(marker))
            window.close()
            self.app.processEvents()
            self.assertFalse(os.path.exists(marker))

    def test_ai_setup_advanced_fields_start_collapsed(self):
        with tempfile.TemporaryDirectory() as root:
            dialog = SimplifiedAISetupDialog(os.path.join(root, "config.json"))
            self.addCleanup(dialog.close)
            self.assertTrue(dialog.api_url.isHidden())
            self.assertTrue(dialog.reasoning_effort.isHidden())
            self.assertTrue(dialog.image_input.isHidden())
            dialog.advanced_toggle.setChecked(True)
            self.app.processEvents()
            self.assertFalse(dialog.reasoning_effort.isHidden())
            self.assertFalse(dialog.image_input.isHidden())


if __name__ == "__main__":
    unittest.main()
