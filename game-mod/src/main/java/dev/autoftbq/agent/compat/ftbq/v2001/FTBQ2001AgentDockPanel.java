package dev.autoftbq.agent.compat.ftbq.v2001;

import dev.autoftbq.agent.bridge.BridgeClient;
import dev.autoftbq.agent.client.AgentContextSelection;
import dev.ftb.mods.ftblibrary.icon.Icon;
import dev.ftb.mods.ftblibrary.ui.Panel;
import dev.ftb.mods.ftblibrary.ui.SimpleTextButton;
import dev.ftb.mods.ftblibrary.ui.TextBox;
import dev.ftb.mods.ftblibrary.ui.Theme;
import dev.ftb.mods.ftblibrary.ui.Widget;
import dev.ftb.mods.ftblibrary.ui.input.MouseButton;
import dev.ftb.mods.ftbquests.client.ClientQuestFile;
import dev.ftb.mods.ftbquests.client.gui.quests.QuestScreen;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.network.chat.Component;
import net.minecraft.util.FormattedCharSequence;
import net.minecraft.util.Mth;

import java.util.ArrayList;
import java.util.List;
import java.util.function.BooleanSupplier;

/** Native FTB Library panel embedded directly in the FTB Quests editor. */
public final class FTBQ2001AgentDockPanel extends Panel {
    private final QuestScreen questScreen;
    private final BooleanSupplier open;
    private TextBox prompt;
    private TranscriptWidget transcript;
    private final List<DockButton> actionButtons = new ArrayList<>();
    private boolean extraActionsVisible;
    private String selectionKey = "";
    private int syncDelay = 1;
    private int studioTransactionPollDelay = 20;
    private int liveBookSyncDelay = 197;

    public FTBQ2001AgentDockPanel(QuestScreen questScreen, BooleanSupplier open) {
        super(questScreen);
        this.questScreen = questScreen;
        this.open = open;
        setOnlyRenderWidgetsInside(true);
        setOnlyInteractWithWidgetsInside(true);
    }

    @Override
    public boolean shouldDraw() {
        return open.getAsBoolean();
    }

    @Override
    public boolean isEnabled() {
        return open.getAsBoolean();
    }

    @Override
    public void addWidgets() {
        transcript = new TranscriptWidget(this);
        add(transcript);

        prompt = new TextBox(this) {
            @Override
            public void onEnterPressed() {
                submitPrompt();
            }
        };
        prompt.setMaxLength(8000);
        refreshPromptHint();
        add(prompt);

        actionButtons.clear();
        actionButtons.add(addAction("screen.autoftbq_agent.submit_short",
                () -> canEditNow() && !BridgeClient.INSTANCE.isBusy()
                        && !prompt.getText().trim().isEmpty(),
                () -> !BridgeClient.INSTANCE.isBusy(), this::submitPrompt));
        actionButtons.add(addAction("screen.autoftbq_agent.cancel",
                BridgeClient.INSTANCE::isBusy,
                BridgeClient.INSTANCE::isBusy, BridgeClient.INSTANCE::cancelRequest));
        actionButtons.add(addAction("screen.autoftbq_agent.pause_resume",
                BridgeClient.INSTANCE::canPauseRequest,
                BridgeClient.INSTANCE::isBusy, BridgeClient.INSTANCE::togglePauseRequest));
        actionButtons.add(addAction("screen.autoftbq_agent.undo_short",
                () -> canEditNow() && BridgeClient.INSTANCE.canUndo(),
                BridgeClient.INSTANCE::canUndo, BridgeClient.INSTANCE::undoLastProposal));
        actionButtons.add(addAction("screen.autoftbq_agent.more",
                () -> true, () -> true, () -> {
                    extraActionsVisible = !extraActionsVisible;
                    alignWidgets();
                }));

        actionButtons.add(addAction("screen.autoftbq_agent.sketch",
                () -> canEditNow() && !BridgeClient.INSTANCE.isBusy(),
                () -> extraActionsVisible && !BridgeClient.INSTANCE.isBusy(),
                () -> Minecraft.getInstance().setScreen(
                        new dev.autoftbq.agent.client.LayoutSketchScreen(Minecraft.getInstance().screen))));
        actionButtons.add(addAction("screen.autoftbq_agent.previous_history",
                BridgeClient.INSTANCE::hasHistory,
                () -> extraActionsVisible && BridgeClient.INSTANCE.hasHistory(),
                BridgeClient.INSTANCE::previousHistory));
        actionButtons.add(addAction("screen.autoftbq_agent.next_history",
                BridgeClient.INSTANCE::isViewingHistory,
                () -> extraActionsVisible && BridgeClient.INSTANCE.hasHistory(),
                BridgeClient.INSTANCE::nextHistory));
        actionButtons.add(addAction("screen.autoftbq_agent.copy_short",
                () -> !BridgeClient.INSTANCE.result().isBlank(),
                () -> extraActionsVisible && !BridgeClient.INSTANCE.result().isBlank(),
                () -> Widget.setClipboardString(BridgeClient.INSTANCE.result())));
        actionButtons.add(addAction("screen.autoftbq_agent.clear_context_short",
                () -> !AgentContextSelection.isEmpty(),
                () -> extraActionsVisible && !AgentContextSelection.isEmpty(), this::clearContext));
    }

    private DockButton addAction(String translationKey, BooleanSupplier enabled,
                                 BooleanSupplier visible, Runnable action) {
        DockButton button = new DockButton(this, Component.translatable(translationKey),
                enabled, visible, action);
        add(button);
        return button;
    }

    private void submitPrompt() {
        if (prompt == null || !canEditNow()) return;
        String value = prompt.getText().trim();
        if (value.isEmpty() || BridgeClient.INSTANCE.isBusy()) return;
        BridgeClient.INSTANCE.submitRequest(value);
        prompt.setText("");
    }

    public String getDraft() { return prompt == null ? "" : prompt.getText(); }
    public void setDraft(String value) { if (prompt != null) prompt.setText(value); }

    private static boolean canEditNow() {
        return ClientQuestFile.INSTANCE != null && ClientQuestFile.INSTANCE.canEdit();
    }

    private void refreshPromptHint() {
        if (prompt == null) return;
        prompt.ghostText = Component.translatable(canEditNow()
                ? "screen.autoftbq_agent.prompt_hint"
                : "screen.autoftbq_agent.prompt_read_only_hint").getString();
    }

    private void clearContext() {
        AgentContextSelection.clear();
        selectionKey = "";
        BridgeClient.INSTANCE.connectAndSync();
    }

    @Override
    public void alignWidgets() {
        int innerWidth = Math.max(120, width - 16);
        int gap = 3;
        int columns = innerWidth >= 340 ? 4 : 3;
        List<DockButton> visibleButtons = new ArrayList<>();
        for (DockButton button : actionButtons) {
            if (button.shouldDraw()) visibleButtons.add(button);
        }
        int rows = Math.max(1, (visibleButtons.size() + columns - 1) / columns);
        int buttonsTop = Math.max(118, height - 8 - rows * 23);
        int promptY = Math.max(92, buttonsTop - 26);
        int transcriptTop = 64;
        transcript.setPosAndSize(8, transcriptTop, innerWidth,
                Math.max(20, promptY - transcriptTop - 6));
        prompt.setPosAndSize(8, promptY, innerWidth, 20);

        int buttonWidth = Math.max(48, (innerWidth - gap * (columns - 1)) / columns);
        for (int index = 0; index < visibleButtons.size(); index++) {
            int column = index % columns;
            int row = index / columns;
            int x = 8 + column * (buttonWidth + gap);
            int y = buttonsTop + row * 23;
            visibleButtons.get(index).setPosAndSize(x, y, buttonWidth, 20);
        }
    }

    @Override
    public void tick() {
        super.tick();
        refreshPromptHint();
        String currentKey = currentSelectionKey();
        if (!currentKey.equals(selectionKey)) {
            selectionKey = currentKey;
            syncDelay = 8;
        }
        if (syncDelay > 0 && --syncDelay == 0) {
            if (BridgeClient.INSTANCE.isBusy()) {
                syncDelay = 2;
            } else {
                BridgeClient.INSTANCE.connectAndSync();
            }
        }
        if (--studioTransactionPollDelay <= 0) {
            studioTransactionPollDelay = 20;
            BridgeClient.INSTANCE.pollStudioTransactions();
        }
        if (--liveBookSyncDelay <= 0) {
            liveBookSyncDelay = 197;
            BridgeClient.INSTANCE.connectAndSync();
        }
    }

    @Override
    public void drawBackground(GuiGraphics graphics, Theme theme,
                               int x, int y, int width, int height) {
        graphics.fill(x, y, x + width, y + height, 0xF21A2420);
        graphics.fill(x, y, x + 2, y + height, 0xFFB7E83F);
        Font font = Minecraft.getInstance().font;
        graphics.drawString(font, Component.translatable("screen.autoftbq_agent.title"),
                x + 10, y + 8, 0xFFFFFFFF, false);
        graphics.drawString(font, contextSummary(), x + 10, y + 23,
                0xFFB8DCCB, false);

        String status = canEditNow() ? BridgeClient.INSTANCE.status()
                : Component.translatable("screen.autoftbq_agent.read_only_status").getString();
        int statusColor = statusColor(status);
        graphics.fill(x + 10, y + 39, x + 15, y + 44, statusColor);
        graphics.drawString(font, font.plainSubstrByWidth(status, Math.max(40, width - 30)),
                x + 20, y + 38, 0xFFA8B5AE, false);
        graphics.drawString(font,
                Component.translatable("screen.autoftbq_agent.mode_auto_apply"),
                x + 10, y + 51, 0xFF82958B, false);
    }

    private int statusColor(String status) {
        String lower = status.toLowerCase(java.util.Locale.ROOT);
        if (status.contains("失败") || status.contains("未连接") || lower.contains("failed")) {
            return 0xFFE36B6B;
        }
        if (BridgeClient.INSTANCE.isBusy()) return 0xFFE7C66A;
        if (canEditNow()) return 0xFF55E6B1;
        return 0xFFE6B855;
    }

    private String contextSummary() {
        int chapters = AgentContextSelection.chapterCount();
        int quests = AgentContextSelection.questCount();
        return chapters == 0 && quests == 0
                ? Component.translatable("screen.autoftbq_agent.context_auto").getString()
                : Component.translatable("screen.autoftbq_agent.context_auto_pinned",
                chapters, quests).getString();
    }

    private String currentSelectionKey() {
        StringBuilder value = new StringBuilder();
        AgentContextSelection.chapterIds().stream().sorted()
                .forEach(id -> value.append("C:").append(id).append('|'));
        AgentContextSelection.questIds().stream().sorted()
                .forEach(id -> value.append("Q:").append(id).append('|'));
        return value.toString();
    }

    private static final class DockButton extends SimpleTextButton {
        private final BooleanSupplier enabled;
        private final BooleanSupplier visible;
        private final Runnable action;

        private DockButton(Panel parent, Component title, BooleanSupplier enabled,
                           BooleanSupplier visible, Runnable action) {
            super(parent, title, Icon.empty());
            this.enabled = enabled;
            this.visible = visible;
            this.action = action;
        }

        @Override
        public boolean isEnabled() {
            return enabled.getAsBoolean();
        }

        @Override
        public boolean shouldDraw() {
            return visible.getAsBoolean();
        }

        @Override
        public boolean renderTitleInCenter() {
            return true;
        }

        @Override
        public void onClicked(MouseButton button) {
            if (isEnabled()) action.run();
        }
    }

    private static final class TranscriptWidget extends Widget {
        private String displayed = "";
        private List<FormattedCharSequence> lines = List.of();
        private int scroll;

        private TranscriptWidget(Panel parent) {
            super(parent);
        }

        @Override
        public void draw(GuiGraphics graphics, Theme theme,
                         int x, int y, int width, int height) {
            graphics.fill(x, y, x + width, y + height, 0xA00D1411);
            Font font = Minecraft.getInstance().font;
            String current = BridgeClient.INSTANCE.result();
            if (!current.equals(displayed)) {
                displayed = current;
                lines = current.isBlank() ? List.of(Component.translatable(
                        "screen.autoftbq_agent.empty").getVisualOrderText())
                        : font.split(Component.literal(current), Math.max(30, width - 12));
                scroll = 0;
            }
            int rows = Math.max(1, (height - 8) / 10);
            int maxScroll = Math.max(0, lines.size() - rows);
            scroll = Mth.clamp(scroll, 0, maxScroll);
            graphics.enableScissor(x + 3, y + 3, x + width - 3, y + height - 3);
            int drawY = y + 4;
            for (int index = scroll; index < lines.size() && index < scroll + rows; index++) {
                graphics.drawString(font, lines.get(index), x + 5, drawY,
                        0xFFE8EFEA, false);
                drawY += 10;
            }
            graphics.disableScissor();
            if (maxScroll > 0) {
                int thumbHeight = Math.max(10, height * rows / lines.size());
                int thumbY = y + (height - thumbHeight) * scroll / maxScroll;
                graphics.fill(x + width - 3, y, x + width, y + height, 0x553D5148);
                graphics.fill(x + width - 3, thumbY, x + width,
                        thumbY + thumbHeight, 0xFFB7E83F);
            }
        }

        @Override
        public boolean mouseScrolled(double delta) {
            int rows = Math.max(1, (height - 8) / 10);
            int maxScroll = Math.max(0, lines.size() - rows);
            scroll = Mth.clamp(scroll - (int) Math.signum(delta) * 3, 0, maxScroll);
            return maxScroll > 0;
        }
    }
}
