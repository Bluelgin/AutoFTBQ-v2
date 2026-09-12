package dev.autoftbq.agent.compat.ftbq.v2001;

import com.mojang.logging.LogUtils;
import dev.autoftbq.agent.client.QuestScreenAgentHost;
import dev.ftb.mods.ftblibrary.util.client.ClientUtils;
import dev.ftb.mods.ftbquests.client.ClientQuestFile;
import dev.ftb.mods.ftbquests.client.gui.quests.QuestScreen;
import net.minecraft.client.Minecraft;

/** Rebind the visible editor after FTBQ replaces its entire client file. */
public final class FTBQ2001ScreenSync {
    private static ClientQuestFile pending;
    private static QuestScreen previousScreen;
    private static QuestScreen.PersistedData view;
    private static long viewedQuest;
    private static int ticks;
    private static boolean wasEditor;

    private FTBQ2001ScreenSync() { }

    public static void beforeReplace(ClientQuestFile replacement) {
        QuestScreen current = ClientUtils.getCurrentGuiAs(QuestScreen.class);
        if (current == null) { clear(); return; }
        // Consecutive full-sync packets can arrive before the first has rendered.
        if (current != previousScreen || pending == null) {
            view = current.getPersistedScreenData();
            viewedQuest = current.getViewedQuest() == null ? 0L : current.getViewedQuest().getId();
            wasEditor = ClientQuestFile.INSTANCE != null && ClientQuestFile.INSTANCE.canEdit();
        }
        pending = replacement;
        previousScreen = current;
        ticks = 0;
        replacement.setPersistedScreenInfo(view);
    }

    public static void tick() {
        if (pending == null) return;
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null || ClientQuestFile.INSTANCE != pending) { clear(); return; }
        QuestScreen current = ClientUtils.getCurrentGuiAs(QuestScreen.class);
        // Never reopen a screen the user has closed or replace another UI.
        if (current != previousScreen) { clear(); return; }
        ticks++;
        boolean teamReady = pending.selfTeamData != null && !pending.selfTeamData.isLocked();
        if (!readyToRebind(teamReady, wasEditor, pending.canEdit(), ticks)) {
            if (ticks == 200) LogUtils.getLogger().warn("AutoFTBQ editor refresh waiting for team data");
            return;
        }
        ClientQuestFile target = pending;
        long questId = viewedQuest;
        // The player may have kept typing while the network data was in flight.
        String savedDraft = ((QuestScreenAgentHost) current).autoftbq$getDraft();
        target.setPersistedScreenInfo(view);
        clear();
        target.clearCachedData();
        QuestScreen fresh = ClientQuestFile.openGui();
        if (fresh != null) {
            if (questId != 0L && target.getQuest(questId) != null) fresh.viewQuest(target.getQuest(questId));
            ((QuestScreenAgentHost) fresh).autoftbq$setDraft(savedDraft);
            LogUtils.getLogger().info("AutoFTBQ editor rebound to synchronized task book");
        }
    }

    public static boolean readyToRebind(boolean teamReady, boolean wasEditor,
                                        boolean canEdit, int elapsedTicks) {
        // A genuine permission revocation must eventually show a read-only
        // window, not leave the old editable one on screen indefinitely.
        return teamReady && (!wasEditor || canEdit || elapsedTicks >= 200);
    }

    private static void clear() {
        pending = null;
        previousScreen = null;
        view = null;
        viewedQuest = 0L;
        ticks = 0;
    }
}
