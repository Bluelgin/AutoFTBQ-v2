package dev.autoftbq.agent.compat.ftbq.v2001.mixin;

import dev.autoftbq.agent.client.QuestScreenAgentHost;
import dev.ftb.mods.ftblibrary.ui.BaseScreen;
import dev.ftb.mods.ftblibrary.ui.input.MouseButton;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * FTBQ opens quest details as a modal panel. FTB Library normally sends all
 * pointer input exclusively to that modal, so the persistent Agent dock needs
 * an explicit hit-tested route above the modal layer.
 */
@Mixin(value = BaseScreen.class, remap = false)
public abstract class BaseScreenAgentInputMixin {
    @Inject(method = "mousePressed", at = @At("HEAD"), cancellable = true)
    private void autoftbq$routeAgentMousePressed(MouseButton button,
                                                  CallbackInfoReturnable<Boolean> callback) {
        if ((Object) this instanceof QuestScreenAgentHost host
                && host.autoftbq$routeAgentMousePressed(button)) {
            callback.setReturnValue(true);
        }
    }

    @Inject(method = "mouseReleased", at = @At("HEAD"), cancellable = true)
    private void autoftbq$routeAgentMouseReleased(MouseButton button,
                                                   CallbackInfo callback) {
        if ((Object) this instanceof QuestScreenAgentHost host
                && host.autoftbq$routeAgentMouseReleased(button)) {
            callback.cancel();
        }
    }

    @Inject(method = "mouseScrolled", at = @At("HEAD"), cancellable = true)
    private void autoftbq$routeAgentMouseScrolled(double delta,
                                                   CallbackInfoReturnable<Boolean> callback) {
        if ((Object) this instanceof QuestScreenAgentHost host
                && host.autoftbq$routeAgentMouseScrolled(delta)) {
            callback.setReturnValue(true);
        }
    }

    @Inject(method = "mouseDragged", at = @At("HEAD"), cancellable = true)
    private void autoftbq$routeAgentMouseDragged(int button, double dragX, double dragY,
                                                  CallbackInfoReturnable<Boolean> callback) {
        if ((Object) this instanceof QuestScreenAgentHost host
                && host.autoftbq$routeAgentMouseDragged(button, dragX, dragY)) {
            callback.setReturnValue(true);
        }
    }
}
