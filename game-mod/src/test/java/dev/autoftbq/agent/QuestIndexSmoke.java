package dev.autoftbq.agent;

import dev.ftb.mods.ftbquests.quest.*;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.world.entity.player.Player;
import dev.architectury.utils.Env;

/** In-memory FTBQ object lifecycle check; no world files are written. */
public final class QuestIndexSmoke {
    private static final class Book extends BaseQuestFile {
        public Env getSide() { return Env.SERVER; }
        public void deleteObject(long id) { }
        public boolean isPlayerOnTeam(Player player, TeamData team) { return false; }
    }
    public static void main(String[] args) {
        net.minecraft.SharedConstants.tryDetectVersion();
        net.minecraft.server.Bootstrap.bootStrap();
        Book book = new Book();
        Chapter chapter = (Chapter) book.create(100L, QuestObjectType.CHAPTER, 0L, new CompoundTag());
        chapter.onCreated();
        book.refreshIDMap();
        if (book.getChapter(100L) != chapter) throw new AssertionError("Chapter not indexed");
        Quest quest = (Quest) book.create(101L, QuestObjectType.QUEST, 100L, new CompoundTag());
        quest.onCreated();
        book.refreshIDMap();
        if (book.getQuest(101L) != quest) throw new AssertionError("Quest not indexed");
        for (String type : new String[]{"kill", "advancement"}) {
            CompoundTag extra = new CompoundTag();
            extra.putString("type", type);
            long id = type.equals("kill") ? 102L : 103L;
            QuestObjectBase task = book.create(id, QuestObjectType.TASK, 101L, extra);
            task.onCreated();
            book.refreshIDMap();
            if (book.getBase(id) != task) throw new AssertionError("Task not indexed: " + type);
        }
        dev.autoftbq.agent.client.AgentDockState.setOpen(true);
        if (!dev.autoftbq.agent.client.AgentDockState.shouldAttach(false))
            throw new AssertionError("Loading permissions discarded the open dock");
        dev.autoftbq.agent.client.AgentDockState.setOpen(false);
        if (!dev.autoftbq.agent.client.AgentDockState.shouldAttach(false))
            throw new AssertionError("Transient missing permission hid the Agent entry");
        if (!dev.autoftbq.agent.client.AgentDockState.shouldAttach(true))
            throw new AssertionError("Editor Agent entry missing after permission recovery");
        if (dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ScreenSync.readyToRebind(false, true, true, 300))
            throw new AssertionError("Refreshed before team data arrived");
        if (dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ScreenSync.readyToRebind(true, true, false, 1))
            throw new AssertionError("Did not wait for editing permissions");
        if (!dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ScreenSync.readyToRebind(true, true, true, 1))
            throw new AssertionError("Did not refresh after permissions arrived");
        if (!dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ScreenSync.readyToRebind(true, true, false, 200))
            throw new AssertionError("Permission revocation blocked read-only refresh");
        System.out.println("FTBQ chapter -> quest index smoke passed");
    }
}
