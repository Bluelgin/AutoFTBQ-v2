package dev.autoftbq.agent.compat.ftbq.v2001;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import dev.autoftbq.agent.compat.ftbq.v2001.mixin.QuestScreenAccessor;
import dev.autoftbq.agent.client.AgentContextSelection;
import dev.autoftbq.agent.platform.ServerSecurityState;
import dev.ftb.mods.ftbquests.client.ClientQuestFile;
import dev.ftb.mods.ftbquests.quest.Chapter;
import dev.ftb.mods.ftbquests.quest.Quest;
import dev.ftb.mods.ftbquests.quest.QuestObjectBase;
import dev.ftb.mods.ftbquests.quest.ChapterGroup;
import dev.ftb.mods.ftbquests.quest.loot.RewardTable;
import net.minecraft.client.Minecraft;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.world.level.storage.LevelResource;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;

/** All direct references to the FTB Quests 2001 API generation live here. */
public final class FTBQ2001ContextAdapter {
    private static String selectionWorldId = "";

    private FTBQ2001ContextAdapter() {
    }

    public static JsonObject capture(String sessionId, int revision,
                                     ServerSecurityState serverSecurity) {
        JsonObject context = new JsonObject();
        context.addProperty("session_id", sessionId);
        context.addProperty("revision", revision);
        String worldId = stableWorldId();
        context.addProperty("world_id", worldId);
        if (!worldId.equals(selectionWorldId)) {
            AgentContextSelection.clear();
            selectionWorldId = worldId;
        }

        JsonArray selectedValues = new JsonArray();
        JsonArray selectedChapterValues = new JsonArray();
        Chapter selectedChapter = null;
        if (ClientQuestFile.exists()) {
            var questScreen = ClientQuestFile.INSTANCE.getQuestScreen();
            if (questScreen.isPresent()) {
                selectedChapter = ((QuestScreenAccessor) questScreen.get()).autoftbq$getSelectedChapter();
            }
            Map<String, Chapter> chapters = new LinkedHashMap<>();
            Map<String, Quest> quests = new LinkedHashMap<>();
            for (Chapter value : ClientQuestFile.INSTANCE.getAllChapters()) {
                chapters.put(value.getCodeString().toUpperCase(), value);
                for (Quest quest : value.getQuests()) {
                    quests.put(quest.getCodeString().toUpperCase(), quest);
                }
            }
            AgentContextSelection.retain(chapters.keySet(), quests.keySet());
            for (String id : AgentContextSelection.chapterIds()) {
                Chapter value = chapters.get(id);
                if (value == null) continue;
                JsonObject chapterValue = new JsonObject();
                chapterValue.addProperty("id", value.getCodeString());
                chapterValue.addProperty("title", value.getTitle().getString());
                JsonArray questIds = new JsonArray();
                value.getQuests().stream().limit(4096)
                        .map(quest -> quest.getCodeString()).forEach(questIds::add);
                chapterValue.add("quest_ids", questIds);
                selectedChapterValues.add(chapterValue);
            }
            for (String id : AgentContextSelection.questIds()) {
                Quest quest = quests.get(id);
                if (quest == null) continue;
                JsonObject value = new JsonObject();
                value.addProperty("id", quest.getCodeString());
                value.addProperty("title", quest.getTitle().getString());
                value.addProperty("chapter_id", quest.getChapter().getCodeString());
                value.addProperty("x", quest.getX());
                value.addProperty("y", quest.getY());
                selectedValues.add(value);
            }
        }
        context.add("selected_chapters", selectedChapterValues);
        context.add("selected_quests", selectedValues);

        JsonObject chapter = new JsonObject();
        if (selectedChapter != null) {
            chapter.addProperty("id", selectedChapter.getCodeString());
            chapter.addProperty("title", selectedChapter.getTitle().getString());
        }
        context.add("chapter", chapter);

        JsonObject book = new JsonObject();
        if (ClientQuestFile.exists()) {
            int chapterCount = ClientQuestFile.INSTANCE.getAllChapters().size();
            int questCount = ClientQuestFile.INSTANCE.getAllChapters().stream()
                    .mapToInt(value -> value.getQuests().size()).sum();
            book.addProperty("chapters", chapterCount);
            book.addProperty("quests", questCount);
            book.addProperty("can_edit", ClientQuestFile.INSTANCE.canEdit());
        }
        context.add("book_summary", book);
        context.addProperty("book_revision", FTBQ2001Revision.compute(
                ClientQuestFile.exists() ? ClientQuestFile.INSTANCE : null));
        context.addProperty("server_book_revision", serverSecurity.bookRevision());
        book.addProperty("server_can_edit", serverSecurity.canEdit());

        JsonObject registries = new JsonObject();
        registries.addProperty("items", BuiltInRegistries.ITEM.size());
        registries.addProperty("blocks", BuiltInRegistries.BLOCK.size());
        registries.addProperty("entities", BuiltInRegistries.ENTITY_TYPE.size());
        context.add("registry_summary", registries);
        return context;
    }

    public static void refreshEmbeddedEditor() {
        Minecraft.getInstance().execute(() -> {
            if (!ClientQuestFile.exists()) return;
            ClientQuestFile.INSTANCE.getQuestScreen().ifPresent(screen ->
                    screen.questPanel.withPreservedPos(panel -> {
                        screen.refreshChapterPanel();
                        screen.refreshQuestPanel();
                        screen.refreshViewQuestPanel();
                    }));
        });
    }

    /** Lossless-enough authoring snapshot using FTBQ's own SNBT writers. */
    public static JsonObject captureBookSnapshot() {
        JsonObject snapshot = new JsonObject();
        snapshot.addProperty("title", "Live FTB Quests");
        JsonArray chapters = new JsonArray();
        JsonArray documents = new JsonArray();
        if (!ClientQuestFile.exists()) {
            snapshot.add("chapters", chapters);
            snapshot.add("documents", documents);
            return snapshot;
        }
        CompoundTag bookData = new CompoundTag();
        ClientQuestFile.INSTANCE.writeData(bookData);
        documents.add(document("data.snbt", bookData));
        CompoundTag groupDocument = new CompoundTag();
        ListTag groups = new ListTag();
        for (ChapterGroup group : ClientQuestFile.INSTANCE.getChapterGroups()) {
            if (group.isDefaultGroup()) continue;
            CompoundTag groupData = new CompoundTag();
            group.writeData(groupData);
            groupData.putString("id", group.getCodeString());
            groups.add(groupData);
        }
        groupDocument.put("chapter_groups", groups);
        documents.add(document("chapter_groups.snbt", groupDocument));
        for (RewardTable table : ClientQuestFile.INSTANCE.getRewardTables()) {
            CompoundTag tableData = new CompoundTag();
            table.writeData(tableData);
            tableData.putString("id", table.getCodeString());
            documents.add(document("reward_tables/" + table.getFilename() + ".snbt", tableData));
        }
        for (Chapter chapter : ClientQuestFile.INSTANCE.getAllChapters()) {
            CompoundTag chapterData = new CompoundTag();
            chapter.writeData(chapterData);
            chapterData.putString("id", chapter.getCodeString());
            if (!chapter.getGroup().isDefaultGroup()) {
                chapterData.putString("group", chapter.getGroup().getCodeString());
            }
            ListTag quests = new ListTag();
            for (Quest quest : chapter.getQuests()) {
                CompoundTag questData = new CompoundTag();
                quest.writeData(questData);
                quest.writeTasks(questData);
                quest.writeRewards(questData);
                questData.putString("id", quest.getCodeString());
                quests.add(questData);
            }
            chapterData.put("quests", quests);
            JsonObject value = new JsonObject();
            value.addProperty("id", chapter.getCodeString());
            value.addProperty("filename", chapter.getFilename());
            value.addProperty("snbt", chapterData.toString());
            chapters.add(value);
        }
        snapshot.add("chapters", chapters);
        snapshot.add("documents", documents);
        snapshot.addProperty("book_revision", FTBQ2001Revision.compute(ClientQuestFile.INSTANCE));
        return snapshot;
    }

    private static JsonObject document(String path, CompoundTag data) {
        JsonObject value = new JsonObject();
        value.addProperty("path", path);
        value.addProperty("snbt", data.toString());
        return value;
    }

    private static String stableWorldId() {
        Minecraft minecraft = Minecraft.getInstance();
        String kind;
        String identity;
        if (minecraft.getSingleplayerServer() != null) {
            kind = "singleplayer";
            identity = minecraft.getSingleplayerServer().getWorldPath(LevelResource.ROOT)
                    .toAbsolutePath().normalize().toString();
        } else if (minecraft.getCurrentServer() != null) {
            kind = "multiplayer";
            identity = minecraft.getCurrentServer().ip.trim().toLowerCase();
        } else {
            kind = "session";
            identity = minecraft.getUser().getUuid();
        }
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(
                    (kind + "\u0000" + identity).getBytes(StandardCharsets.UTF_8));
            return kind + ":" + HexFormat.of().formatHex(digest, 0, 16);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

}
