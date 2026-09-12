package dev.autoftbq.agent.compat.ftbq.v2001.mixin;

import dev.autoftbq.agent.bridge.BridgeClient;
import dev.autoftbq.agent.client.AgentContextSelection;
import dev.autoftbq.agent.client.AgentDockState;
import dev.ftb.mods.ftblibrary.ui.Theme;
import dev.ftb.mods.ftblibrary.ui.input.MouseButton;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.screens.Screen;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(targets = "dev.ftb.mods.ftbquests.client.gui.quests.ChapterPanel$ChapterButton", remap = false)
public abstract class ChapterButtonAgentContextMixin {
    @Inject(method = "onClicked", at = @At("HEAD"), cancellable = true)
    private void autoftbq$toggleAgentChapter(MouseButton button, CallbackInfo callback) {
        if (!AgentDockState.isOpen() || !button.isLeft() || !Screen.hasAltDown()) return;
        String id = ((ChapterButtonAccessor) this).autoftbq$getChapter().getCodeString();
        AgentContextSelection.toggleChapter(id);
        BridgeClient.INSTANCE.connectAndSync();
        callback.cancel();
    }

    @Inject(method = "draw", at = @At("TAIL"))
    private void autoftbq$drawAgentChapterSelection(GuiGraphics graphics, Theme theme,
                                                     int x, int y, int width, int height,
                                                     CallbackInfo callback) {
        if (!AgentDockState.isOpen()) return;
        String id = ((ChapterButtonAccessor) this).autoftbq$getChapter().getCodeString();
        if (AgentContextSelection.containsChapter(id)) {
            graphics.renderOutline(x, y, width, height, 0xFF55E6B1);
            graphics.renderOutline(x + 1, y + 1, Math.max(1, width - 2),
                    Math.max(1, height - 2), 0xAA55E6B1);
        }
    }
}
