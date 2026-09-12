package dev.autoftbq.agent.compat.ftbq.v2001.mixin;

import dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ScreenSync;
import dev.ftb.mods.ftbquests.client.ClientQuestFile;
import dev.ftb.mods.ftbquests.quest.BaseQuestFile;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(value = ClientQuestFile.class, remap = false)
public abstract class ClientQuestFileSyncMixin {
    @Inject(method = "syncFromServer", at = @At("HEAD"))
    private static void autoftbq$preserveEditorBeforeReplace(BaseQuestFile replacement, CallbackInfo ci) {
        if (replacement instanceof ClientQuestFile file) FTBQ2001ScreenSync.beforeReplace(file);
    }
}
