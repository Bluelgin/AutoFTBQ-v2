package dev.autoftbq.agent.compat.ftbq.v2001.mixin;

import dev.autoftbq.agent.bridge.BridgeClient;
import dev.autoftbq.agent.client.AgentDockState;
import dev.autoftbq.agent.client.QuestScreenAgentHost;
import dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001AgentDockPanel;
import dev.ftb.mods.ftblibrary.icon.Icon;
import dev.ftb.mods.ftblibrary.ui.Panel;
import dev.ftb.mods.ftblibrary.ui.SimpleTextButton;
import dev.ftb.mods.ftblibrary.ui.Widget;
import dev.ftb.mods.ftblibrary.ui.input.MouseButton;
import dev.ftb.mods.ftbquests.client.ClientQuestFile;
import dev.ftb.mods.ftbquests.client.gui.quests.QuestScreen;
import net.minecraft.network.chat.Component;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(value = QuestScreen.class, remap = false)
public abstract class QuestScreenAgentMixin implements QuestScreenAgentHost {
    @Unique
    private FTBQ2001AgentDockPanel autoftbq$dock;
    @Unique
    private SimpleTextButton autoftbq$toggle;
    @Unique
    private boolean autoftbq$agentMouseCaptured;

    @Override
    public String autoftbq$getDraft() {
        return autoftbq$dock == null ? "" : autoftbq$dock.getDraft();
    }

    @Override
    public void autoftbq$setDraft(String value) {
        if (autoftbq$dock != null) autoftbq$dock.setDraft(value);
    }

    @Inject(method = "addWidgets", at = @At("TAIL"))
    private void autoftbq$addAgentWidgets(CallbackInfo callback) {
        QuestScreen screen = (QuestScreen) (Object) this;
        if (!AgentDockState.shouldAttach(ClientQuestFile.INSTANCE.canEdit())) {
            autoftbq$dock = null;
            autoftbq$toggle = null;
            return;
        }
        Panel root = screen;
        autoftbq$dock = new FTBQ2001AgentDockPanel(screen,
                AgentDockState::isOpen);
        root.add(autoftbq$dock);
        autoftbq$toggle = SimpleTextButton.create(root,
                Component.translatable("screen.autoftbq_agent.toggle"), Icon.empty(),
                mouse -> autoftbq$toggleAgentDock());
        root.add(autoftbq$toggle);
    }

    @Inject(method = "alignWidgets", at = @At("TAIL"))
    private void autoftbq$alignAgentWidgets(CallbackInfo callback) {
        autoftbq$layoutAgent();
    }

    @Unique
    private void autoftbq$layoutAgent() {
        QuestScreen screen = (QuestScreen) (Object) this;
        if (autoftbq$dock == null || autoftbq$toggle == null) return;
        int dockWidth = Math.max(300, Math.min(480, screen.getWidth() * 2 / 5));
        autoftbq$dock.setPosAndSize(screen.getWidth() - dockWidth, 0,
                dockWidth, screen.getHeight());
        autoftbq$dock.alignWidgets();
        int toggleX = AgentDockState.isOpen()
                ? screen.getWidth() - dockWidth - 46 : screen.getWidth() - 46;
        autoftbq$toggle.setPosAndSize(Math.max(2, toggleX), 4, 42, 20);
        autoftbq$layoutQuestDetails(screen, dockWidth);
    }

    @Unique
    private void autoftbq$layoutQuestDetails(QuestScreen screen, int dockWidth) {
        if (screen.getViewedQuest() == null) return;
        int usableWidth = AgentDockState.isOpen()
                ? screen.getWidth() - dockWidth : screen.getWidth();
        int centeredX = (usableWidth - screen.viewQuestPanel.getWidth()) / 2;
        int maxX = Math.max(4, usableWidth - screen.viewQuestPanel.getWidth() - 8);
        screen.viewQuestPanel.setX(Math.max(4, Math.min(centeredX, maxX)));
    }

    @Inject(method = "viewQuest", at = @At("TAIL"))
    private void autoftbq$keepQuestDetailsClearOfDock(
            dev.ftb.mods.ftbquests.quest.Quest quest, CallbackInfo callback) {
        autoftbq$layoutAgent();
    }

    @Inject(method = "refreshViewQuestPanel", at = @At("TAIL"))
    private void autoftbq$keepRefreshedQuestDetailsClearOfDock(CallbackInfo callback) {
        autoftbq$layoutAgent();
    }

    @Override
    public void autoftbq$toggleAgentDock() {
        if (!ClientQuestFile.INSTANCE.canEdit() && !AgentDockState.isOpen()) return;
        boolean opened = AgentDockState.toggle();
        autoftbq$layoutAgent();
        if (opened) BridgeClient.INSTANCE.connectAndSync();
    }

    @Override
    public boolean autoftbq$isAgentDockOpen() {
        return AgentDockState.isOpen();
    }

    @Override
    public boolean autoftbq$routeAgentMousePressed(MouseButton button) {
        if (autoftbq$isInside(autoftbq$toggle)) {
            autoftbq$agentMouseCaptured = true;
            autoftbq$toggle.mousePressed(button);
            return true;
        }
        if (AgentDockState.isOpen() && autoftbq$isInside(autoftbq$dock)) {
            autoftbq$agentMouseCaptured = true;
            autoftbq$dock.mousePressed(button);
            return true;
        }
        autoftbq$agentMouseCaptured = false;
        return false;
    }

    @Override
    public boolean autoftbq$routeAgentMouseReleased(MouseButton button) {
        if (!autoftbq$agentMouseCaptured
                && !(AgentDockState.isOpen() && autoftbq$isInside(autoftbq$dock))
                && !autoftbq$isInside(autoftbq$toggle)) {
            return false;
        }
        if (autoftbq$dock != null) autoftbq$dock.mouseReleased(button);
        if (autoftbq$toggle != null) autoftbq$toggle.mouseReleased(button);
        autoftbq$agentMouseCaptured = false;
        return true;
    }

    @Override
    public boolean autoftbq$routeAgentMouseScrolled(double delta) {
        if (!AgentDockState.isOpen() || !autoftbq$isInside(autoftbq$dock)) return false;
        autoftbq$dock.mouseScrolled(delta);
        return true;
    }

    @Override
    public boolean autoftbq$routeAgentMouseDragged(int button, double dragX, double dragY) {
        if (!autoftbq$agentMouseCaptured) return false;
        if (autoftbq$dock != null) autoftbq$dock.mouseDragged(button, dragX, dragY);
        return true;
    }

    @Unique
    private boolean autoftbq$isInside(Widget widget) {
        if (widget == null || !widget.isEnabled() || !widget.shouldDraw()) return false;
        QuestScreen screen = (QuestScreen) (Object) this;
        int mouseX = screen.getMouseX();
        int mouseY = screen.getMouseY();
        return mouseX >= widget.getX() && mouseX < widget.getX() + widget.getWidth()
                && mouseY >= widget.getY() && mouseY < widget.getY() + widget.getHeight();
    }
}
