package dev.autoftbq.agent.compat.ftbq.v2001.mixin;

import dev.autoftbq.agent.bridge.BridgeClient;
import dev.autoftbq.agent.client.AgentContextSelection;
import dev.autoftbq.agent.client.AgentDockState;
import dev.ftb.mods.ftblibrary.ui.input.MouseButton;
import dev.ftb.mods.ftbquests.client.gui.quests.QuestButton;
import net.minecraft.client.gui.screens.Screen;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(value = QuestButton.class, remap = false)
public abstract class QuestButtonAgentContextMixin {
    @Inject(method = "onClicked", at = @At("HEAD"), cancellable = true)
    private void autoftbq$toggleAgentQuest(MouseButton button, CallbackInfo callback) {
        if (!AgentDockState.isOpen() || !button.isLeft() || !Screen.hasAltDown()) return;
        String id = ((QuestButtonAccessor) this).autoftbq$getQuest().getCodeString();
        AgentContextSelection.toggleQuest(id);
        BridgeClient.INSTANCE.connectAndSync();
        callback.cancel();
    }
}
