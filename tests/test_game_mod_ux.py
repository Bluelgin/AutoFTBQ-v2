import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "game-mod"


class GameModUxTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (MOD / relative).read_text(encoding="utf-8")

    def test_agent_dock_uses_progressive_actions(self):
        source = self.read(
            "src/main/java/dev/autoftbq/agent/compat/ftbq/v2001/FTBQ2001AgentDockPanel.java"
        )
        self.assertIn('"screen.autoftbq_agent.more"', source)
        self.assertIn("extraActionsVisible", source)
        self.assertIn("BooleanSupplier visible", source)
        self.assertIn('"screen.autoftbq_agent.mode_auto_apply"', source)
        self.assertIn('"screen.autoftbq_agent.context_auto_pinned"', source)

    def test_agent_dock_can_open_before_edit_permission_arrives(self):
        source = self.read(
            "src/main/java/dev/autoftbq/agent/compat/ftbq/v2001/mixin/QuestScreenAgentMixin.java"
        )
        method = source.split("public void autoftbq$toggleAgentDock()", 1)[1].split(
            "@Override", 1
        )[0]
        self.assertIn("AgentDockState.toggle()", method)
        self.assertNotIn("canEdit()", method)

    def test_g_key_can_open_ftbq_in_read_only_mode(self):
        source = self.read("src/main/java/dev/autoftbq/agent/forge/AutoFTBQForgeClient.java")
        self.assertIn("else if (ClientQuestFile.exists())", source)
        self.assertNotIn("ClientQuestFile.exists() && ClientQuestFile.INSTANCE.canEdit()", source)

    def test_language_files_cover_new_ux_keys(self):
        required = {
            "screen.autoftbq_agent.more",
            "screen.autoftbq_agent.context_auto",
            "screen.autoftbq_agent.context_auto_pinned",
            "screen.autoftbq_agent.read_only_status",
            "screen.autoftbq_agent.mode_auto_apply",
            "screen.autoftbq_agent.prompt_read_only_hint",
            "screen.autoftbq_agent.sketch_more",
            "screen.autoftbq_agent.sketch_preview_message",
        }
        for locale in ("zh_cn.json", "en_us.json"):
            path = MOD / "src/main/resources/assets/autoftbq_agent/lang" / locale
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(required.issubset(data), f"missing keys in {locale}: {required - set(data)}")

    def test_layout_sketch_uses_translation_keys_for_controls(self):
        source = self.read("src/main/java/dev/autoftbq/agent/client/LayoutSketchScreen.java")
        self.assertIn('tr("screen.autoftbq_agent.sketch_pen")', source)
        self.assertIn('tr("screen.autoftbq_agent.sketch_more")', source)
        self.assertIn("extraTools", source)
        self.assertNotIn('Component.literal("自由手绘布局', source)


if __name__ == "__main__":
    unittest.main()
