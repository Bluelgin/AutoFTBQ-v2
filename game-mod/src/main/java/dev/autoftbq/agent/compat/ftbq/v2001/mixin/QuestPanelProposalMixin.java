package dev.autoftbq.agent.compat.ftbq.v2001.mixin;

import dev.autoftbq.agent.bridge.BridgeClient;
import dev.autoftbq.agent.client.AgentContextSelection;
import dev.autoftbq.agent.client.AgentDockState;
import dev.ftb.mods.ftblibrary.ui.Theme;
import dev.ftb.mods.ftblibrary.ui.Widget;
import dev.ftb.mods.ftbquests.client.gui.quests.QuestButton;
import dev.ftb.mods.ftbquests.client.gui.quests.QuestPanel;
import net.minecraft.client.gui.GuiGraphics;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(value = QuestPanel.class, remap = false)
public abstract class QuestPanelProposalMixin {
    @Inject(method = "draw", at = @At("TAIL"))
    private void autoftbq$drawProposalHighlights(GuiGraphics graphics, Theme theme,
                                                  int x, int y, int width, int height,
                                                  CallbackInfo callback) {
        if (!AgentDockState.isOpen()) return;
        QuestPanel panel = (QuestPanel) (Object) this;
        for (Widget widget : panel.getWidgets()) {
            if (!(widget instanceof QuestButton button)) continue;
            String id = ((QuestButtonAccessor) button).autoftbq$getQuest()
                    .getCodeString().toUpperCase();
            int left = button.getX() - 2;
            int top = button.getY() - 2;
            int right = left + button.getWidth() + 4;
            int bottom = top + button.getHeight() + 4;
            if (AgentContextSelection.containsQuest(id)) {
                graphics.renderOutline(left, top, right - left, bottom - top, 0xFF55E6B1);
                graphics.renderOutline(left - 1, top - 1,
                        right - left + 2, bottom - top + 2, 0x9955E6B1);
            }
            if (BridgeClient.INSTANCE.isProposalAffectedQuest(id)) {
                graphics.renderOutline(left - 2, top - 2,
                        right - left + 4, bottom - top + 4, 0xFFB7E83F);
            }
        }
    }
}
