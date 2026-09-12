import os
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QScrollArea, QVBoxLayout, QWidget

from autoftbq_v2.infrastructure.asset_index import ItemAsset
from autoftbq_v2.ftb.schema import REWARD_TYPES, TASK_TYPES
from autoftbq_v2.ftb_store import FTBQuestStore
from autoftbq_v2.ui import (
    ChapterImageNode,
    CurvedDependencyLine,
    DependencyLine,
    FormWheelNavigationFilter,
    IconPickerDialog,
    ItemPickerDialog,
    MainWindow,
    ModpackScanThread,
    QuestLinkNode,
    QuestNode,
    RegistryPickerDialog,
    apply_light_palette,
)
from snbt_parser import parse_snbt, to_snbt


class FakeAssetIndex:
    def __init__(self):
        self.items = {
            "minecraft:iron_ingot": ItemAsset("minecraft:iron_ingot", "铁锭"),
            "create:shaft": ItemAsset("create:shaft", "传动杆"),
            "create:brass_ingot": ItemAsset("create:brass_ingot", "黄铜锭"),
        }

    def icon_for(self, _item_id):
        return ""

    def quest_shapes(self):
        return ["diamond", "heart", "gear"]

    def summary(self):
        return {"resources": len(self.items)}


class V2UiTests(unittest.TestCase):
    def test_game_backend_locks_desktop_and_preserves_draft_on_disconnect(self):
        window = MainWindow(restore_workspace=False)
        self.addCleanup(window.close)
        original = window.store
        service = Mock()
        service.snapshot.return_value = {
            "available": True, "project_id": "world-a", "session_id": "session-a",
            "conversation_id": "chat-a", "seconds_since_sync": 0,
            "server_can_edit": True,
        }
        service.events.return_value = []
        window.bridge_server = Mock(service=service)
        with patch.object(window, "_process_game_agent_requests"):
            window._refresh_game_bridge_status()
            self.assertTrue(window._game_backend_mode)
            self.assertFalse(window.desktop_workspace.isEnabled())
            self.assertEqual(window.workspace_modes.currentIndex(), 1)
            window.new_project()
            window.open_live_game_book()
            window.sync_live_game_book()
            self.assertIs(window.store, original)
            service.queue_studio_book.assert_not_called()
            service.snapshot.return_value = {"available": False}
            window._refresh_game_bridge_status()
            self.assertIn("中断", window.backend_status.text())
            self.assertFalse(window.desktop_workspace.isEnabled())

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_light_palette_covers_unstyled_dynamic_controls(self):
        apply_light_palette(self.app)

        palette = self.app.palette()
        self.assertEqual(palette.color(QPalette.ColorRole.Window).name(), "#f3f1eb")
        self.assertEqual(palette.color(QPalette.ColorRole.WindowText).name(), "#202722")
        self.assertEqual(palette.color(QPalette.ColorRole.Base).name(), "#fffefb")
        self.assertEqual(palette.color(QPalette.ColorRole.Text).name(), "#202722")

    def test_window_uses_studio_product_name(self):
        window = MainWindow(restore_workspace=False)
        window.show()
        self.app.processEvents()
        self.assertEqual(window.windowTitle(), "AutoFTBQ Studio")
        brand = window.findChild(QLabel, "brandName")
        self.assertIsNotNone(brand)
        self.assertEqual(brand.text().replace("\n", " "), "AutoFTBQ Studio")
        widest_line = max(brand.fontMetrics().horizontalAdvance(line) for line in brand.text().splitlines())
        self.assertGreaterEqual(brand.width(), widest_line)
        window.close()

    def test_agent_progress_is_empty_when_no_request_is_active(self):
        window = MainWindow(restore_workspace=False)

        self.assertEqual(window.agent_progress_bar.minimum(), 0)
        self.assertEqual(window.agent_progress_bar.maximum(), 100)
        self.assertEqual(window.agent_progress_bar.value(), 0)
        self.assertEqual(window.agent_progress_bar.format(), "")

        window.update_agent_progress("agent_plan", '{"request":"测试任务"}')
        window.update_agent_progress("agent_commit", "{}")
        self.assertEqual(window.agent_progress_bar.maximum(), 100)
        self.assertEqual(window.agent_progress_bar.value(), 0)
        self.assertEqual(window.agent_progress_bar.format(), "")
        self.assertEqual(window.agent_current_label.text(), "当前：等待下一条要求")
        window.close()

    def test_agent_finish_clears_stale_progress_and_keeps_only_interruption_message(self):
        window = MainWindow(restore_workspace=False)
        window.agent_progress_bar.setRange(0, 3)
        window.agent_progress_bar.setValue(2)
        window.agent_current_label.setText("当前：等待下一条要求")

        window.agent_finished()
        self.assertEqual(window.agent_progress_bar.maximum(), 100)
        self.assertEqual(window.agent_progress_bar.value(), 0)

        window.agent_progress_bar.setRange(0, 3)
        window.agent_progress_bar.setValue(2)
        window._agent_attention_message = "当前：检查点已保留，可发送“继续”恢复执行"
        window.agent_finished()
        self.assertEqual(window.agent_progress_bar.maximum(), 100)
        self.assertEqual(window.agent_progress_bar.value(), 0)
        self.assertEqual(window.agent_progress_bar.format(), "")
        self.assertIn("继续", window.agent_current_label.text())
        window.close()

    def test_workspace_restore_does_not_replay_historical_progress(self):
        with tempfile.TemporaryDirectory() as root:
            first = MainWindow(workspace_dir=root)
            first._workspace_enabled = True
            first._workspace_ready = True
            first.append_action("agent_plan", '{"request":"历史任务"}', refresh=False)
            first.append_action("agent_repair", "{}", refresh=False)
            first._save_workspace_snapshot()
            first.close()

            restored = MainWindow(restore_workspace=True, workspace_dir=root)

            self.assertTrue(any(row["name"] == "agent_repair" for row in restored.action_records))
            self.assertGreater(restored.action_list.count(), 0)
            self.assertEqual(restored.agent_progress_bar.minimum(), 0)
            self.assertEqual(restored.agent_progress_bar.maximum(), 100)
            self.assertEqual(restored.agent_progress_bar.value(), 0)
            self.assertEqual(restored.agent_progress_bar.format(), "")
            self.assertEqual(restored.agent_current_label.text(), "当前：等待下一条要求")
            restored.close()

    def test_canvas_uses_nonblocking_cached_icon_lookup(self):
        class NonBlockingIndex:
            def __init__(self):
                self.cached_calls = 0

            def cached_icon_for(self, _item_id):
                self.cached_calls += 1
                return ""

            def cached_image_for(self, _image_id):
                return ""

            def icon_for(self, _item_id):
                raise AssertionError("chapter switching must not render icons synchronously")

        window = MainWindow(restore_workspace=False)
        index = NonBlockingIndex()
        window.asset_index = index

        window.refresh_canvas()

        self.assertGreater(index.cached_calls, 0)
        window.close()

    def test_canvas_expands_when_view_approaches_right_edge(self):
        window = MainWindow(restore_workspace=False)
        window.show()
        self.app.processEvents()
        before = window.scene.sceneRect()

        window.canvas.centerOn(before.right(), before.center().y())
        window.canvas.ensure_scene_space()
        after = window.scene.sceneRect()

        self.assertGreater(after.right(), before.right())
        self.assertEqual(after.left(), before.left())
        window.close()

    def test_canvas_refresh_does_not_shrink_explored_area_in_same_chapter(self):
        window = MainWindow(restore_workspace=False)
        expanded = window.scene.sceneRect().adjusted(-4000, -3000, 5000, 3000)
        window.scene.setSceneRect(expanded)

        window.refresh_canvas()

        refreshed = window.scene.sceneRect()
        self.assertLessEqual(refreshed.left(), expanded.left())
        self.assertGreaterEqual(refreshed.right(), expanded.right())
        window.close()

    def test_fit_canvas_uses_content_instead_of_expanded_scene(self):
        window = MainWindow(restore_workspace=False)
        window.show()
        self.app.processEvents()
        window.scene.setSceneRect(-100000, -100000, 200000, 200000)

        window.fit_canvas()

        content = window.scene.itemsBoundingRect()
        visible = window.canvas.viewport_scene_rect()
        self.assertTrue(visible.contains(content))
        self.assertGreater(window.canvas.transform().m11(), 0.1)
        window.close()

    def test_workspace_snapshot_records_scene_center(self):
        with tempfile.TemporaryDirectory() as root:
            window = MainWindow(workspace_dir=root)
            window._workspace_enabled = True
            window._workspace_ready = True
            window.canvas.centerOn(1840.0, -620.0)
            self.app.processEvents()

            window._save_workspace_snapshot()

            loaded = window.workspace_repository.load()
            self.assertIn("center_x", loaded.session["view"])
            self.assertIn("center_y", loaded.session["view"])
            window.close()

    def test_combo_wheel_scrolls_form_without_changing_selection(self):
        class WheelEvent:
            @staticmethod
            def type():
                return QEvent.Type.Wheel

            @staticmethod
            def angleDelta():
                return QPoint(0, -120)

        scroll = QScrollArea()
        scroll.resize(260, 120)
        content = QWidget()
        content.setMinimumHeight(800)
        layout = QVBoxLayout(content)
        combo = QComboBox(content)
        combo.addItems(["第一个", "第二个", "第三个"])
        layout.addWidget(combo)
        layout.addStretch(1)
        scroll.setWidget(content)
        scroll.show()
        self.app.processEvents()

        initial_index = combo.currentIndex()
        initial_scroll = scroll.verticalScrollBar().value()
        handled = FormWheelNavigationFilter().eventFilter(combo, WheelEvent())

        self.assertTrue(handled)
        self.assertEqual(combo.currentIndex(), initial_index)
        self.assertGreater(scroll.verticalScrollBar().value(), initial_scroll)
        scroll.close()

    def test_workspace_restores_draft_conversation_and_selection(self):
        with tempfile.TemporaryDirectory() as root:
            first = MainWindow(workspace_dir=root)
            first._workspace_enabled = True
            first._workspace_ready = True
            chapter = first.store.project.chapters[0]
            quest = chapter.quests[0]
            first.store.update_quest(quest.id, title="未保存任务")
            first.current_chapter_id = chapter.id
            first.current_quest_id = quest.id
            first.append_chat("user", "继续完善这一章")
            first.append_chat("agent", "我会从当前内容继续。")
            first.append_action("update_quest", quest.id, refresh=False)
            first.prompt.setPlainText("尚未发送的要求")
            first._restored_agent_history = [
                {"role": "user", "content": "上一轮要求"},
                {"role": "assistant", "content": "上一轮结果"},
            ]
            first._restored_agent_run_state = {
                "request": "创建主线", "baseline": {}, "steps": [], "criteria": [],
                "phase": "needs_attention", "attempts": 1, "failures": ["任务不足"], "actions": [],
            }
            first.agent_context_quest_ids.add(quest.id)
            first._restored_agent_request_context = {
                "intent": "improve", "strict": True, "quest_ids": [quest.id],
            }
            first._save_workspace_snapshot()
            first.close()

            restored = MainWindow(restore_workspace=True, workspace_dir=root)

            self.assertEqual(restored.store.project.chapters[0].quests[0].title, "未保存任务")
            self.assertEqual(restored.current_chapter_id, chapter.id)
            self.assertEqual(restored.current_quest_id, quest.id)
            self.assertEqual(restored.prompt.toPlainText(), "尚未发送的要求")
            self.assertTrue(any(value["text"] == "继续完善这一章" for value in restored.chat_records))
            self.assertTrue(any(value["name"] == "update_quest" for value in restored.action_records))
            self.assertEqual(restored._restored_agent_history[-1]["content"], "上一轮结果")
            self.assertEqual(restored._restored_agent_run_state["request"], "创建主线")
            self.assertEqual(restored.agent_progress_bar.value(), 0)
            self.assertEqual(restored.agent_progress_bar.format(), "")
            self.assertIn("继续", restored.agent_current_label.text())
            self.assertEqual(restored.agent_context_quest_ids, {quest.id})
            self.assertEqual(restored._restored_agent_request_context["intent"], "improve")
            restored.close()

    def test_alt_click_toggles_quest_agent_context_without_changing_editor_selection(self):
        window = MainWindow()
        window.show()
        self.app.processEvents()
        node = next(item for item in window.scene.items() if isinstance(item, QuestNode))
        original_quest_id = window.current_quest_id
        point = window.canvas.mapFromScene(node.sceneBoundingRect().center())

        QTest.mouseClick(
            window.canvas.viewport(), Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier, point,
        )
        QTest.qWait(5)

        self.assertIn(node.quest.id, window.agent_context_quest_ids)
        self.assertEqual(window.current_quest_id, original_quest_id)
        self.assertIn("任务：", window.agent_context_label.text())
        window.close()

    def test_slash_improve_requires_scope_and_selected_task_builds_strict_request(self):
        window = MainWindow()

        structured, scope, clarification = window.prepare_structured_agent_request("/改进 优化描述")
        self.assertIsNone(structured)
        self.assertIsNone(scope)
        self.assertIn("Alt + 点击", clarification)

        quest = window.store.project.chapters[0].quests[0]
        window.toggle_agent_quest_context(quest.id)
        structured, scope, clarification = window.prepare_structured_agent_request("/改进 优化描述")

        self.assertFalse(clarification)
        self.assertIn("执行模式：改进", structured)
        self.assertTrue(scope["strict"])
        self.assertEqual(scope["quest_ids"], [quest.id])
        window.close()

    def test_natural_language_improve_does_not_require_explicit_scope(self):
        window = MainWindow()

        structured, scope, clarification = window.prepare_structured_agent_request(
            "帮我完善一下目前的任务内容"
        )

        self.assertFalse(clarification)
        self.assertIn("执行模式：改进", structured)
        self.assertFalse(scope["strict"])
        window.close()

    def test_prompt_is_queued_while_agent_is_busy(self):
        window = MainWindow()
        window.ai_configured = True
        window.agent_thread = object()
        window.prompt.setPlainText("接下来再检查一次任务书")

        window.send_to_agent()

        self.assertEqual(window.agent_prompt_queue, ["接下来再检查一次任务书"])
        self.assertFalse(window.prompt.toPlainText())
        self.assertIn("加入队列", window.send_button.text())
        window.agent_thread = None
        window.close()

    def test_agent_progress_shows_plan_checkpoints_and_validation(self):
        window = MainWindow()

        window.update_agent_progress("agent_plan", '{"request":"创建 Boss 挑战章节"}')
        window.update_agent_progress(
            "agent_checkpoint", '{"index":2,"label":"已完成 T0 任务"}',
        )
        window.update_agent_progress("agent_verify", '{"passed":true,"failures":[]}')

        progress_text = "\n".join(
            window.agent_progress_list.item(index).text()
            for index in range(window.agent_progress_list.count())
        )
        self.assertEqual(window.agent_goal_label.text(), "创建 Boss 挑战章节")
        self.assertIn("检查点 2", progress_text)
        self.assertEqual(window.agent_progress_bar.value(), 3)
        self.assertIn("验收通过", window.agent_progress_bar.format())
        window.close()

    def test_agent_progress_marks_unqueried_but_safe_id_as_warning(self):
        window = MainWindow()

        window.update_agent_progress(
            "agent_id_unverified",
            '{"message":"使用了真实且安全、但本轮未先查询的 ID",'
            '"ids":[{"registry":"item","id":"create:shaft"}]}',
        )

        item = window.agent_progress_list.item(window.agent_progress_list.count() - 1)
        self.assertIn("提醒", item.text())
        self.assertIn("create:shaft", item.text())
        self.assertEqual(item.foreground().color().name(), "#8a6400")
        window.close()

    def test_ui_can_undo_only_the_latest_agent_checkpoint(self):
        window = MainWindow()
        agent = __import__("autoftbq_v2.agent", fromlist=["ProjectAgent"]).ProjectAgent(
            window.store, None,
        )
        agent._begin_transaction()
        chapter_id = __import__("json").loads(
            agent.call_tool("create_chapter", {"title": "Boss 挑战"})
        )["chapter_id"]
        agent.call_tool("add_quest", {
            "chapter_id": chapter_id, "title": "末影龙", "task_type": "checkmark",
        })
        window.agent = agent

        window.undo_agent_checkpoint()

        self.assertIsNotNone(window.store.chapter(chapter_id))
        self.assertEqual(window.store.chapter(chapter_id).quests, [])
        self.assertEqual(agent.checkpoint_count, 1)
        window.close()

    def test_agent_failure_keeps_safe_checkpoint_in_editor(self):
        window = MainWindow()
        agent = __import__("autoftbq_v2.agent", fromlist=["ProjectAgent"]).ProjectAgent(
            window.store, None,
        )
        agent._begin_transaction()
        chapter_id = __import__("json").loads(
            agent.call_tool("create_chapter", {"title": "断线前成果"})
        )["chapter_id"]
        window.agent = agent

        window.agent_failed("网络暂时中断")

        self.assertIsNotNone(window.store.chapter(chapter_id))
        self.assertTrue(agent.has_pending_changes)
        self.assertIn("安全检查点", window.chat.toPlainText())
        self.assertEqual(window.agent_progress_bar.maximum(), 100)
        self.assertEqual(window.agent_progress_bar.value(), 0)
        self.assertEqual(window.agent_progress_bar.format(), "")
        self.assertIn("继续", window.agent_current_label.text())
        window.close()

    def test_slash_menu_sets_command_and_mode(self):
        window = MainWindow()

        window.select_agent_command("/润色")

        self.assertEqual(window.prompt.toPlainText(), "/润色 ")
        self.assertEqual(window.prompt_mode.text(), "润色")
        self.assertEqual(len(window.command_menu.actions()), 8)
        window.close()

    def test_workspace_automatically_restores_last_modpack_resources(self):
        calls = []

        class TrackingWindow(MainWindow):
            def _start_modpack_scan(self, folder, *, automatic=False, preserve_store=False):
                calls.append((folder, automatic, preserve_store))
                return True

        with tempfile.TemporaryDirectory() as root:
            workspace = os.path.join(root, "workspace")
            modpack = os.path.join(root, "pack")
            os.makedirs(modpack)
            first = MainWindow(workspace_dir=workspace)
            first._workspace_enabled = True
            first._workspace_ready = True
            first.store.project.mod_folder = modpack
            first._save_workspace_snapshot()
            first.close()

            restored = TrackingWindow(restore_workspace=True, workspace_dir=workspace)
            QTest.qWait(150)

            self.assertEqual(calls, [(os.path.abspath(modpack), True, True)])
            self.assertEqual(restored.last_modpack_folder, os.path.abspath(modpack))
            restored.close()

    def test_automatic_resource_scan_does_not_replace_restored_draft(self):
        with tempfile.TemporaryDirectory() as root:
            window = MainWindow()
            window.store.project.title = "未保存的草稿"
            original_store = window.store
            disk_store = FTBQuestStore.create_new("游戏内任务书")
            window._automatic_scan = True
            window._scan_preserve_store = True
            window.fit_canvas = lambda: self.fail("自动资源恢复不应重置画布视角")

            window._scan_completed({
                "folder": root,
                "items": {},
                "recipes": {},
                "asset_index": FakeAssetIndex(),
                "quest_root": os.path.join(root, "config", "ftbquests", "quests"),
                "store": disk_store,
            })

            self.assertIs(window.store, original_store)
            self.assertEqual(window.store.project.title, "未保存的草稿")
            self.assertEqual(window.store.project.mod_folder, root)
            self.assertIn("未覆盖当前草稿", window.modpack_status.text())
            window.close()

    def test_manual_scan_keeps_selected_folder_after_loading_quest_book(self):
        with tempfile.TemporaryDirectory() as root:
            window = MainWindow()
            disk_store = FTBQuestStore.create_new("游戏内任务书")
            disk_store.project.mod_folder = ""
            window._automatic_scan = False
            window._scan_preserve_store = False

            window._scan_completed({
                "folder": root,
                "items": {},
                "recipes": {},
                "asset_index": FakeAssetIndex(),
                "quest_root": os.path.join(root, "config", "ftbquests", "quests"),
                "store": disk_store,
            })

            self.assertEqual(window.store.project.mod_folder, root)
            self.assertEqual(window.last_modpack_folder, root)
            window.close()

    def test_invalid_restored_modpack_path_is_reported_without_scanning(self):
        window = MainWindow()
        window.store.project.mod_folder = os.path.join(tempfile.gettempdir(), "missing-autoftbq-pack")

        window._restore_last_modpack()

        self.assertIsNone(window.scan_thread)
        self.assertIn("路径已失效", window.modpack_status.text())
        self.assertIn("重新选择", window.scan_button.text())
        window.close()

    def test_two_click_connection_updates_project(self):
        window = MainWindow()
        chapter = window.store.chapter(window.current_chapter_id)
        first = chapter.quests[0]
        second = window.store.add_quest(chapter.id, "Second")
        third = window.store.add_quest(chapter.id, "Third")
        third.dependencies.clear()
        window.refresh_all()

        window.toggle_connect_mode(True)
        window._handle_connection_click(first)
        window._handle_connection_click(third)

        self.assertIn(first.id, window.store.quest(third.id)[1].dependencies)
        self.assertTrue(window.connect_mode)
        window.close()

    def test_new_workspace_exposes_full_typed_condition_editor(self):
        window = MainWindow()
        quest = window.store.project.chapters[0].quests[0]
        window.current_quest_id = quest.id
        window.load_inspector(quest)
        pane = window.sections_editor.tasks
        pane.add_type.setCurrentIndex(pane.add_type.findData("dimension"))

        pane.add_object()

        tasks, _ = window.store.raw_sections(quest.id)
        self.assertEqual(tasks[-1]["type"], "dimension")
        self.assertEqual(tasks[-1]["dimension"], "minecraft:overworld")
        self.assertIn("共 2 条", window.condition_summary.text())
        self.assertTrue(pane.raw.isHidden())
        window.close()

    def test_startup_and_chapter_switch_select_a_real_quest(self):
        window = MainWindow()
        first_chapter = window.store.project.chapters[0]

        self.assertEqual(window.current_quest_id, first_chapter.quests[0].id)
        self.assertEqual(window.sections_editor.tasks.quest_id, first_chapter.quests[0].id)
        selected = [item for item in window.scene.selectedItems() if isinstance(item, QuestNode)]
        self.assertEqual([item.quest.id for item in selected], [first_chapter.quests[0].id])

        second_chapter = window.store.create_chapter("第二章")
        second_quest = window.store.add_quest(second_chapter.id, "第二章任务")
        window.refresh_all()
        chapter_item = next(
            window.chapter_list.item(row)
            for row in range(window.chapter_list.count())
            if window.chapter_list.item(row).data(Qt.ItemDataRole.UserRole) == second_chapter.id
        )
        window.chapter_list.setCurrentItem(chapter_item)

        self.assertEqual(window.current_quest_id, second_quest.id)
        self.assertEqual(window.sections_editor.tasks.quest_id, second_quest.id)
        window.close()

    def test_editor_integrates_chapters_scan_validation_and_agent(self):
        window = MainWindow()
        window.show()
        self.app.processEvents()

        self.assertFalse(hasattr(window, "view_stack"))
        self.assertTrue(window.chapter_list.isVisible())
        self.assertTrue(window.canvas.isVisible())
        self.assertTrue(window.chat.isVisible())
        self.assertTrue(window.prompt.isVisible())
        window.show_validation()
        self.app.processEvents()
        self.assertTrue(window.validation_list.isVisible())
        self.assertEqual(window.workspace_splitter.count(), 3)
        self.assertIn("扫描", window.modpack_status.text())
        window.close()

    def test_agent_busy_mode_allows_chapter_navigation_and_restores_editing(self):
        window = MainWindow()
        second_chapter = window.store.create_chapter("Agent 工作时可查看")
        second_quest = window.store.add_quest(second_chapter.id, "查看中的任务")
        window.refresh_all()
        window.ai_configured = True

        window.set_agent_busy(True)

        self.assertTrue(window.chapter_panel.isEnabled())
        self.assertTrue(window.chapter_list.isEnabled())
        self.assertTrue(window.editor_panel.isEnabled())
        self.assertFalse(window.editor_tabs.isEnabled())
        self.assertTrue(window.prompt.isEnabled())
        self.assertTrue(window.send_button.isEnabled())
        self.assertIn("加入队列", window.send_button.text())
        chapter_item = next(
            window.chapter_list.item(row)
            for row in range(window.chapter_list.count())
            if window.chapter_list.item(row).data(Qt.ItemDataRole.UserRole) == second_chapter.id
        )
        window.chapter_list.setCurrentItem(chapter_item)
        self.assertEqual(window.current_chapter_id, second_chapter.id)
        self.assertEqual(window.current_quest_id, second_quest.id)
        node = next(item for item in window.scene.items() if isinstance(item, QuestNode))
        self.assertFalse(node.flags() & QuestNode.GraphicsItemFlag.ItemIsMovable)
        self.assertTrue(node.flags() & QuestNode.GraphicsItemFlag.ItemIsSelectable)

        window.set_agent_busy(False)

        self.assertTrue(window.editor_tabs.isEnabled())
        self.assertTrue(window.send_button.isEnabled())
        node = next(item for item in window.scene.items() if isinstance(item, QuestNode))
        self.assertTrue(node.flags() & QuestNode.GraphicsItemFlag.ItemIsMovable)
        window.close()

    def test_chat_roles_keep_readable_explicit_colors(self):
        window = MainWindow()
        window.chat.clear()

        window.append_chat("user", "创建一个章节")
        window.append_chat("agent", "已经完成")
        window.append_chat("error", "测试错误")
        html = window.chat.toHtml().casefold()

        self.assertIn("#173f33", html)
        self.assertIn("#26322c", html)
        self.assertIn("#712f25", html)
        self.assertNotIn("#f3f6f4", html)
        window.close()

    def test_background_scan_worker_returns_index_without_touching_widgets(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "mods"))
            results = []
            worker = ModpackScanThread(root, os.path.join(root, "cache"))
            worker.completed.connect(results.append)

            worker.run()

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["folder"], root)
            self.assertEqual(results[0]["items"], {})
            self.assertIsNone(results[0]["store"])

    def test_one_prerequisite_can_branch_to_multiple_quests_without_moving_nodes(self):
        window = MainWindow()
        chapter = window.store.chapter(window.current_chapter_id)
        source = chapter.quests[0]
        second = window.store.add_quest(chapter.id, "Second")
        third = window.store.add_quest(chapter.id, "Third")
        window.store.move_quest(source.id, -1.5, 2.0)
        window.store.move_quest(second.id, 2.25, -1.0)
        window.store.move_quest(third.id, 5.5, 3.25)
        expected_positions = {
            quest.id: (quest.x, quest.y)
            for quest in (source, second, third)
        }
        window.refresh_all()

        window.toggle_connect_mode(True)
        window._handle_connection_click(source)
        window._handle_connection_click(second)
        window._handle_connection_click(source)
        window._handle_connection_click(third)

        self.assertEqual(window.store.quest(second.id)[1].dependencies, [source.id])
        self.assertEqual(window.store.quest(third.id)[1].dependencies, [source.id])
        actual_positions = {
            quest.id: (quest.x, quest.y)
            for quest in (source, second, third)
        }
        self.assertEqual(actual_positions, expected_positions)
        scene_positions = {
            item.quest.id: (round(item.pos().x() / 72, 2), round(item.pos().y() / 72, 2))
            for item in window.scene.items()
            if isinstance(item, QuestNode)
        }
        self.assertEqual(scene_positions, expected_positions)
        self.assertEqual(
            len([item for item in window.scene.items() if isinstance(item, DependencyLine)]),
            2,
        )
        window.close()

    def test_scene_selection_can_create_shared_prerequisite_without_rebuild(self):
        window = MainWindow()
        chapter = window.store.chapter(window.current_chapter_id)
        source = chapter.quests[0]
        second = window.store.add_quest(chapter.id, "Second")
        third = window.store.add_quest(chapter.id, "Third")
        window.refresh_all()
        nodes = {
            item.quest.id: item
            for item in window.scene.items()
            if isinstance(item, QuestNode)
        }

        window.toggle_connect_mode(True)
        for target in (second, third):
            window.scene.clearSelection()
            nodes[source.id].setSelected(True)
            window.scene.clearSelection()
            nodes[target.id].setSelected(True)
            self.app.processEvents()

        self.assertEqual(window.store.quest(second.id)[1].dependencies, [source.id])
        self.assertEqual(window.store.quest(third.id)[1].dependencies, [source.id])
        self.assertEqual(
            len([item for item in window.scene.items() if isinstance(item, DependencyLine)]),
            2,
        )
        self.assertIs(nodes[source.id].scene(), window.scene)
        self.assertIs(nodes[second.id].scene(), window.scene)
        self.assertIs(nodes[third.id].scene(), window.scene)
        window.close()

    def test_duplicate_and_cycle_connections_are_rejected_without_mutation(self):
        window = MainWindow()
        chapter = window.store.chapter(window.current_chapter_id)
        source = chapter.quests[0]
        target = window.store.add_quest(chapter.id, "Target")
        window.refresh_all()

        window._handle_connection_click(source)
        window._handle_connection_click(target)
        undo_count = len(window.store._undo)
        window._handle_connection_click(source)
        window._handle_connection_click(target)

        self.assertEqual(window.store.quest(target.id)[1].dependencies, [source.id])
        self.assertEqual(len(window.store._undo), undo_count)
        self.assertIn("已经连接", window.connection_hint.text())

        window._handle_connection_click(target)
        window._handle_connection_click(source)
        self.assertEqual(window.store.quest(source.id)[1].dependencies, [])
        self.assertIn("循环依赖", window.connection_hint.text())
        window.close()

    def test_normal_mode_drag_position_is_saved_for_project_store(self):
        window = MainWindow()
        chapter = window.store.chapter(window.current_chapter_id)
        quest = chapter.quests[0]
        node = next(item for item in window.scene.items() if isinstance(item, QuestNode))

        node.setPos(QPointF(252, -108))
        node.on_move(quest.id, node.pos())
        window.toggle_connect_mode(True)
        window.refresh_all()

        self.assertEqual((quest.x, quest.y), (3.5, -1.5))
        refreshed = next(item for item in window.scene.items() if isinstance(item, QuestNode))
        self.assertEqual(refreshed.pos(), QPointF(252, -108))
        window.close()

    def test_agent_mutation_action_refreshes_canvas(self):
        window = MainWindow()
        chapter = window.store.chapter(window.current_chapter_id)
        window.store.add_quest(chapter.id, "Live quest")

        window.append_action("add_quest", "live")

        node_ids = {
            item.data(0)
            for item in window.scene.items()
            if hasattr(item, "data") and item.data(0)
        }
        self.assertEqual(len(node_ids), len(chapter.quests))
        window.close()

    def test_agent_mutation_refreshes_selected_quest_inspector(self):
        window = MainWindow()
        quest = window.store.chapter(window.current_chapter_id).quests[0]
        window.current_quest_id = quest.id
        window.load_inspector(quest)
        window.store.update_quest(quest.id, title="Agent 修改后的标题")

        window.append_action("update_quest", quest.id)

        self.assertEqual(window.quest_title.text(), "Agent 修改后的标题")
        titles = [
            item.quest.title
            for item in window.scene.items()
            if isinstance(item, QuestNode)
        ]
        self.assertIn("Agent 修改后的标题", titles)
        window.close()

    def test_dependency_line_follows_moved_node(self):
        window = MainWindow()
        chapter = window.store.chapter(window.current_chapter_id)
        second = window.store.add_quest(chapter.id, "Second")
        window.store.connect(second.id, chapter.quests[0].id)
        window.refresh_all()
        edge = next(item for item in window.scene.items() if isinstance(item, DependencyLine))
        source = next(
            item for item in window.scene.items()
            if isinstance(item, QuestNode) and item.quest.id == chapter.quests[0].id
        )
        before = QPointF(edge.line().p1())

        source.setPos(source.pos() + QPointF(100, 40))

        self.assertNotEqual(edge.line().p1(), before)
        self.assertEqual(edge.line().p1(), source.sceneBoundingRect().center())
        window.close()

    def test_canvas_renders_official_bezier_control_points_and_hidden_lines(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root = os.path.join(root, "config", "ftbquests", "quests")
            chapters = os.path.join(quest_root, "chapters")
            os.makedirs(chapters)
            with open(os.path.join(chapters, "chapter.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt({
                    "id": "10", "title": "Curves", "quests": [
                        {"id": "20", "title": "A", "x": 0.0, "y": 0.0,
                         "tasks": [{"id": "30", "type": "checkmark"}], "rewards": [], "dependencies": []},
                        {"id": "21", "title": "B", "x": 4.0, "y": 0.0,
                         "tasks": [{"id": "31", "type": "checkmark"}], "rewards": [],
                         "dependencies": ["20"], "dep_control_pts": {"20": [1.0, -2.0, 3.0, 2.0]}},
                    ],
                }))
            store = FTBQuestStore.load_directory(quest_root, root)
            window = MainWindow()
            window.store = store
            window.current_chapter_id = "10"
            window.refresh_all()

            curve = next(item for item in window.scene.items() if isinstance(item, CurvedDependencyLine))
            self.assertEqual(curve.controls, [1.0, -2.0, 3.0, 2.0])
            self.assertEqual(curve.path().elementCount(), 4)
            store.update_quest_fields("21", {"hide_dependency_lines": True})
            window.refresh_canvas()
            self.assertFalse(any(isinstance(item, (DependencyLine, CurvedDependencyLine)) for item in window.scene.items()))
            window.close()

    def test_manual_add_creates_unique_unconnected_quest(self):
        window = MainWindow()
        chapter = window.store.chapter(window.current_chapter_id)
        expected_center = window.canvas.mapToScene(window.canvas.viewport().rect().center())

        window.add_quest()
        first_added = chapter.quests[-1]
        window.add_quest()

        self.assertEqual([quest.title for quest in chapter.quests[-2:]], ["新任务 2", "新任务 3"])
        self.assertEqual(chapter.quests[-1].dependencies, [])
        self.assertEqual(
            (first_added.x, first_added.y),
            (round(expected_center.x() / 72, 2), round(expected_center.y() / 72, 2)),
        )
        window.close()

    def test_canvas_copy_paste_rekeys_quest_and_places_it_in_view(self):
        window = MainWindow()
        chapter = window.store.chapter(window.current_chapter_id)
        source = chapter.quests[0]
        node = next(item for item in window.scene.items() if isinstance(item, QuestNode))
        node.setSelected(True)
        center = window.canvas.mapToScene(window.canvas.viewport().rect().center())

        window.copy_canvas_selection()
        window.paste_canvas_selection(with_dependencies=False)

        self.assertEqual(len(chapter.quests), 2)
        copied = chapter.quests[-1]
        self.assertNotEqual(copied.id, source.id)
        self.assertEqual(copied.dependencies, [])
        self.assertEqual(
            (copied.x, copied.y),
            (round(center.x() / 72, 2), round(center.y() / 72, 2)),
        )
        window.close()

    def test_basic_properties_do_not_overwrite_completion_conditions(self):
        window = MainWindow()
        quest = window.store.chapter(window.current_chapter_id).quests[0]
        window.store.add_quest_object(quest.id, "task", "dimension", {"dimension": "minecraft:the_nether"})
        window.current_quest_id = quest.id
        window.load_inspector(quest)
        window.quest_shape.setCurrentIndex(window.quest_shape.findData("rsquare"))
        window.quest_type.setCurrentIndex(window.quest_type.findData("item"))
        window.quest_target.setText("create:shaft")

        window.apply_quest_changes()

        updated = window.store.quest(quest.id)[1]
        self.assertEqual(updated.shape, "rsquare")
        self.assertEqual([task.type for task in updated.tasks], ["checkmark", "dimension"])
        self.assertIn("2", window.condition_summary.text())
        window.close()

    def test_shape_selector_preserves_unknown_value_and_can_choose_default(self):
        window = MainWindow()
        quest = window.store.chapter(window.current_chapter_id).quests[0]
        quest.shape = "custom_pack_shape"
        window.current_quest_id = quest.id

        window.load_inspector(quest)
        self.assertEqual(window.quest_shape.currentData(), "custom_pack_shape")
        window.quest_shape.setCurrentIndex(window.quest_shape.findData(""))
        window.apply_quest_changes()

        self.assertEqual(window.store.quest(quest.id)[1].shape, "")
        window.close()

    def test_item_picker_searches_name_and_id_and_returns_selection(self):
        picker = ItemPickerDialog(FakeAssetIndex())

        picker.search.setText("黄铜")
        self.assertEqual(picker.results.count(), 1)
        self.assertEqual(
            picker.results.item(0).data(Qt.ItemDataRole.UserRole),
            "create:brass_ingot",
        )
        picker.search.setText("create:shaft")
        picker.accept_selection()

        self.assertEqual(picker.selected_id, "create:shaft")
        picker.close()

    def test_icon_picker_searches_grid_and_returns_selection(self):
        class CachedIndex(FakeAssetIndex):
            def cached_icon_for(self, _item_id):
                return ""

            def icon_status_text(self, _item_id):
                return ""

        picker = IconPickerDialog(CachedIndex())
        picker.search.setText("create")

        self.assertEqual(picker.results.count(), 2)
        picker.results.setCurrentRow(1)
        expected = picker.results.currentItem().data(Qt.ItemDataRole.UserRole)
        picker.accept_selection()

        self.assertEqual(picker.selected_id, expected)
        picker.close()

    def test_quest_icon_shortcuts_use_target_and_clear_override(self):
        window = MainWindow()
        quest = window.store.chapter(window.current_chapter_id).quests[0]
        window.current_quest_id = quest.id
        window.load_inspector(quest)
        window.quest_type.setCurrentIndex(window.quest_type.findData("item"))
        window.quest_target.setText("minecraft:iron_ingot")

        window.use_target_as_quest_icon()
        self.assertEqual(window.quest_icon.text(), "minecraft:iron_ingot")
        window.clear_quest_icon()
        self.assertEqual(window.quest_icon.text(), "")
        self.assertEqual(window.quest_icon_preview.text(), "自动")
        window.close()

    def test_generic_registry_picker_searches_readable_names_and_ids(self):
        picker = RegistryPickerDialog("选择群系", {
            "minecraft:plains": "平原",
            "sample:crystal_caves": "水晶洞穴",
        })
        picker.search.setText("水晶")
        self.assertEqual(picker.results.count(), 1)
        picker.accept_selection()
        self.assertEqual(picker.selected_id, "sample:crystal_caves")
        picker.close()

    def test_inspector_changes_sync_without_apply_button(self):
        window = MainWindow()
        quest = window.store.chapter(window.current_chapter_id).quests[0]
        window.current_quest_id = quest.id
        window.load_inspector(quest)

        window.quest_title.setText("实时更新后的标题")
        window.quest_title.textEdited.emit(window.quest_title.text())
        QTest.qWait(360)

        self.assertEqual(window.store.quest(quest.id)[1].title, "实时更新后的标题")
        self.assertEqual(window.autosave_state.text(), "已实时同步")
        titles = [
            item.quest.title
            for item in window.scene.items()
            if isinstance(item, QuestNode)
        ]
        self.assertIn("实时更新后的标题", titles)
        window.close()

    def test_shape_selector_only_lists_ftb_core_shapes(self):
        window = MainWindow()
        values = [window.quest_shape.itemData(index) for index in range(window.quest_shape.count())]

        self.assertEqual(values, ["", "circle", "square", "rsquare", "none"])
        window.close()

    def test_shape_selector_loads_theme_extensions_and_draws_distinct_paths(self):
        window = MainWindow()
        window.asset_index = FakeAssetIndex()
        window.refresh_shape_choices()
        values = [window.quest_shape.itemData(index) for index in range(window.quest_shape.count())]

        self.assertEqual(values[-3:], ["diamond", "heart", "gear"])
        self.assertNotEqual(QuestNode.shape_path("diamond").elementCount(), QuestNode.shape_path("circle").elementCount())
        self.assertGreater(QuestNode.shape_path("gear").elementCount(), QuestNode.shape_path("hexagon").elementCount())
        window.close()

    def test_structured_editor_manages_multiple_official_tasks_and_rewards(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root = os.path.join(root, "config", "ftbquests", "quests")
            chapters = os.path.join(quest_root, "chapters")
            os.makedirs(chapters)
            chapter_raw = {
                "id": "1000000000000001", "title": "Test", "quests": [{
                    "id": "2000000000000001", "title": "Quest", "x": 0.0, "y": 0.0,
                    "tasks": [{"id": "3000000000000001", "type": "checkmark"}],
                    "rewards": [], "dependencies": [],
                }],
            }
            with open(os.path.join(chapters, "chapter.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt(chapter_raw))
            store = FTBQuestStore.load_directory(quest_root, root)
            window = MainWindow()
            window.store = store
            window.current_chapter_id = store.project.chapters[0].id
            window.current_quest_id = store.project.chapters[0].quests[0].id
            window.refresh_all()

            task_pane = window.sections_editor.tasks
            reward_pane = window.sections_editor.rewards
            self.assertEqual(task_pane.add_type.count(), len(TASK_TYPES))
            self.assertEqual(reward_pane.add_type.count(), len(REWARD_TYPES))
            task_pane.add_type.setCurrentIndex(task_pane.add_type.findData("kill"))
            task_pane.add_object()
            reward_pane.add_type.setCurrentIndex(reward_pane.add_type.findData("command"))
            reward_pane.add_object()

            tasks, rewards = store.raw_sections(window.current_quest_id)
            self.assertEqual([task["type"] for task in tasks], ["checkmark", "kill"])
            self.assertEqual([reward["type"] for reward in rewards], ["command"])
            task_pane.move_object(-1)
            self.assertEqual(store.raw_sections(window.current_quest_id)[0][0]["type"], "kill")
            window.close()

    def test_structured_editor_preserves_unknown_addon_type_in_raw_mode(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root = os.path.join(root, "config", "ftbquests", "quests")
            chapters = os.path.join(quest_root, "chapters")
            os.makedirs(chapters)
            raw = {
                "id": "1", "title": "Test", "quests": [{
                    "id": "2", "title": "Quest", "x": 0.0, "y": 0.0,
                    "tasks": [{"id": "3", "type": "addon:energy", "energy": 9000, "custom": {"keep": 1}}],
                    "rewards": [], "dependencies": [],
                }],
            }
            with open(os.path.join(chapters, "chapter.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt(raw))
            store = FTBQuestStore.load_directory(quest_root, root)
            window = MainWindow()
            quest = store.project.chapters[0].quests[0]
            window.store = store
            window.current_chapter_id = store.project.chapters[0].id
            window.current_quest_id = quest.id
            window.refresh_all()

            pane = window.sections_editor.tasks
            self.assertEqual(pane.type_combo.currentData(), "addon:energy")
            self.assertIn("energy", pane.raw.toPlainText())
            self.assertEqual(store.raw_sections(quest.id)[0][0]["custom"], {"keep": 1})
            window.close()

    def test_advanced_quest_chapter_and_book_properties_sync_in_real_time(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root = os.path.join(root, "config", "ftbquests", "quests")
            chapters = os.path.join(quest_root, "chapters")
            os.makedirs(chapters)
            chapter_raw = {
                "id": "10", "title": "Chapter", "unknown_chapter": 1,
                "quests": [{
                    "id": "20", "title": "Quest", "x": 0.0, "y": 0.0,
                    "tasks": [{"id": "30", "type": "checkmark"}], "rewards": [],
                    "dependencies": [], "unknown_quest": {"keep": True},
                }],
            }
            with open(os.path.join(chapters, "chapter.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt(chapter_raw))
            with open(os.path.join(quest_root, "data.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt({"version": 13, "unknown_book": 2}))
            store = FTBQuestStore.load_directory(quest_root, root)
            window = MainWindow()
            quest = store.project.chapters[0].quests[0]
            window.store = store
            window.current_chapter_id = store.project.chapters[0].id
            window.current_quest_id = quest.id
            window.refresh_all()

            quest_props = parse_snbt(window.quest_properties.raw.toPlainText())
            quest_props["can_repeat"] = True
            window.quest_properties.raw.setPlainText(to_snbt(quest_props))
            chapter_props = parse_snbt(window.chapter_properties.raw.toPlainText())
            chapter_props["require_sequential_tasks"] = True
            window.chapter_properties.raw.setPlainText(to_snbt(chapter_props))
            book_props = parse_snbt(window.book_properties.raw.toPlainText())
            book_props["grid_scale"] = 1.25
            window.book_properties.raw.setPlainText(to_snbt(book_props))
            QTest.qWait(420)

            self.assertTrue(store.quest_data(quest.id)["can_repeat"])
            self.assertEqual(store.quest_data(quest.id)["unknown_quest"], {"keep": True})
            self.assertTrue(store.chapter_data(store.project.chapters[0].id)["require_sequential_tasks"])
            self.assertEqual(store.chapter_data(store.project.chapters[0].id)["unknown_chapter"], 1)
            self.assertEqual(store.document("data.snbt")["grid_scale"], 1.25)
            self.assertEqual(store.document("data.snbt")["unknown_book"], 2)
            window.close()

    def test_chapter_group_and_reward_table_managers_use_real_documents(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root = os.path.join(root, "config", "ftbquests", "quests")
            chapters = os.path.join(quest_root, "chapters")
            os.makedirs(chapters)
            with open(os.path.join(chapters, "chapter.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt({
                    "id": "10", "title": "Chapter", "quests": [{
                        "id": "20", "title": "Quest", "x": 0.0, "y": 0.0,
                        "tasks": [{"id": "30", "type": "checkmark"}], "rewards": [], "dependencies": [],
                    }],
                }))
            with open(os.path.join(quest_root, "chapter_groups.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt({"chapter_groups": []}))
            store = FTBQuestStore.load_directory(quest_root, root)
            window = MainWindow()
            window.store = store
            window.current_chapter_id = store.project.chapters[0].id
            window.refresh_all()

            window.chapter_groups_editor.add_group()
            window.reward_tables_editor.add_table()
            reward_pane = window.reward_tables_editor.rewards
            reward_pane.add_type.setCurrentIndex(reward_pane.add_type.findData("item"))
            reward_pane.add_object()

            self.assertEqual(len(store.document_objects("chapter_groups.snbt", "chapter_groups")), 1)
            tables = store.list_reward_tables()
            self.assertEqual(len(tables), 1)
            self.assertEqual(store.document_objects(tables[0]["path"], "rewards")[0]["type"], "item")
            window.close()

    def test_chapter_images_and_links_render_move_and_survive_reload(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root = os.path.join(root, "config", "ftbquests", "quests")
            chapters = os.path.join(quest_root, "chapters")
            os.makedirs(chapters)
            first = {
                "id": "10", "title": "First", "quests": [{
                    "id": "20", "title": "Source", "x": 0.0, "y": 0.0,
                    "tasks": [{"id": "30", "type": "checkmark"}], "rewards": [], "dependencies": [],
                }],
            }
            second = {
                "id": "11", "title": "Second", "quests": [{
                    "id": "21", "title": "Target", "x": 2.0, "y": 1.0,
                    "tasks": [{"id": "31", "type": "checkmark"}], "rewards": [], "dependencies": [],
                }],
            }
            for filename, raw in (("first.snbt", first), ("second.snbt", second)):
                with open(os.path.join(chapters, filename), "w", encoding="utf-8") as handle:
                    handle.write(to_snbt(raw))
            store = FTBQuestStore.load_directory(quest_root, root)
            window = MainWindow()
            window.store = store
            window.current_chapter_id = "10"
            window.refresh_all()

            image = store.add_chapter_object("10", "image", {
                "image": "minecraft:textures/item/book.png", "x": 1.0, "y": 2.0,
                "width": 2.0, "height": 1.0, "position_locked": True,
                "addon_field": {"keep": True},
            })
            link = store.add_chapter_object("10", "link", {
                "linked_quest": "21", "x": 3.0, "y": 4.0, "shape": "circle",
            })
            window.refresh_all()

            image_node = next(item for item in window.scene.items() if isinstance(item, ChapterImageNode))
            link_node = next(item for item in window.scene.items() if isinstance(item, QuestLinkNode))
            self.assertEqual(image_node.pos(), QPointF(72, 144))
            self.assertFalse(image_node.flags() & image_node.GraphicsItemFlag.ItemIsMovable)
            self.assertEqual(link_node.linked_quest, "21")
            image_node.setSelected(True)
            window.select_canvas_quest()
            self.assertEqual(window.chapter_objects_editor.images.current_id, image["id"])
            window._chapter_image_moved(image["id"], QPointF(180, -36))
            window._quest_link_moved(link["id"], QPointF(288, 72))
            store.save()

            reloaded = FTBQuestStore.load_directory(quest_root, root)
            raw = reloaded.chapter_data("10")
            self.assertEqual((raw["images"][0]["x"], raw["images"][0]["y"]), (2.5, -0.5))
            self.assertEqual(raw["images"][0]["addon_field"], {"keep": True})
            self.assertEqual((raw["quest_links"][0]["x"], raw["quest_links"][0]["y"]), (4.0, 1.0))
            window.open_linked_quest("21")
            self.assertEqual(window.current_chapter_id, "11")
            self.assertEqual(window.current_quest_id, "21")
            window.close()

    def test_translation_editor_uses_native_locale_documents_in_real_time(self):
        with tempfile.TemporaryDirectory() as root:
            quest_root = os.path.join(root, "config", "ftbquests", "quests")
            chapters = os.path.join(quest_root, "chapters")
            os.makedirs(chapters)
            with open(os.path.join(chapters, "chapter.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt({
                    "id": "10", "title": "Chapter", "quests": [{
                        "id": "20", "title": "Quest", "x": 0.0, "y": 0.0,
                        "tasks": [{"id": "30", "type": "checkmark"}], "rewards": [], "dependencies": [],
                    }],
                }))
            with open(os.path.join(quest_root, "data.snbt"), "w", encoding="utf-8") as handle:
                handle.write(to_snbt({"version": 13, "fallback_locale": "en_us"}))
            store = FTBQuestStore.load_directory(quest_root, root)
            window = MainWindow()
            window.store = store
            window.current_chapter_id = "10"
            window.refresh_all()

            editor = window.translations_editor
            editor.locale.setCurrentText("zh_cn")
            editor.object_type.setCurrentIndex(editor.object_type.findData("quest"))
            editor._refresh_objects()
            editor.object_id.setCurrentIndex(editor.object_id.findData("20"))
            editor.field.setCurrentIndex(editor.field.findData("title"))
            editor.value.setPlainText("任务标题")
            QTest.qWait(420)

            self.assertEqual(store.translation_entries("zh_cn")["quest.20.title"], "任务标题")
            window.close()


if __name__ == "__main__":
    unittest.main()
