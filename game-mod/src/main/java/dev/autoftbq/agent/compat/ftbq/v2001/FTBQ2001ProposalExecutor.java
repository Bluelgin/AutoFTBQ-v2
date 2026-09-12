package dev.autoftbq.agent.compat.ftbq.v2001;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import dev.ftb.mods.ftbquests.net.SyncQuestsMessage;
import dev.ftb.mods.ftbquests.net.SyncEditorPermissionMessage;
import dev.ftb.mods.ftbquests.integration.PermissionsHelper;
import dev.ftb.mods.ftbquests.quest.Chapter;
import dev.ftb.mods.ftbquests.quest.ChapterGroup;
import dev.ftb.mods.ftbquests.quest.Quest;
import dev.ftb.mods.ftbquests.quest.QuestObject;
import dev.ftb.mods.ftbquests.quest.QuestObjectBase;
import dev.ftb.mods.ftbquests.quest.QuestObjectType;
import dev.ftb.mods.ftbquests.quest.ServerQuestFile;
import dev.ftb.mods.ftbquests.quest.reward.ItemReward;
import dev.ftb.mods.ftbquests.quest.reward.XPLevelsReward;
import dev.ftb.mods.ftbquests.quest.reward.XPReward;
import dev.ftb.mods.ftbquests.quest.reward.Reward;
import dev.ftb.mods.ftbquests.quest.loot.RewardTable;
import dev.ftb.mods.ftbquests.quest.task.CheckmarkTask;
import dev.ftb.mods.ftbquests.quest.task.ItemTask;
import dev.ftb.mods.ftbquests.quest.task.XPTask;
import dev.ftb.mods.ftbquests.quest.task.Task;
import dev.ftb.mods.ftbquests.util.NBTUtils;
import io.netty.buffer.Unpooled;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.nbt.TagParser;
import net.minecraft.network.FriendlyByteBuf;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/** Server-only bounded transaction executor for the reviewed proposal subset. */
public final class FTBQ2001ProposalExecutor {
    private static final int MAX_OPERATIONS = 1000;
    private static final int MAX_UNDO_BYTES = 16 * 1024 * 1024;
    private static final Map<UUID, UndoRecord> LAST_UNDO = new ConcurrentHashMap<>();
    private static final Map<UUID, UndoneRecord> LAST_UNDONE = new ConcurrentHashMap<>();

    private FTBQ2001ProposalExecutor() {
    }

    public static Result apply(ServerPlayer player, String proposalId,
                               String expectedRevision, String operationsJson) {
        ServerQuestFile file = ServerQuestFile.INSTANCE;
        if (file == null) {
            return Result.failure("failed", "FTB Quests 服务端任务书尚未加载");
        }
        var security = FTBQ2001ServerSecurity.snapshot(player);
        if (!security.canEdit()) {
            return Result.failure("failed", "服务器拒绝了 FTB Quests 编辑权限");
        }
        UndoRecord previous = LAST_UNDO.get(player.getUUID());
        if (previous != null && previous.proposalId.equals(proposalId)) {
            if (previous.beforeRevision.equals(expectedRevision)
                    && previous.operationsJson.equals(operationsJson)
                    && previous.afterRevision.equals(security.bookRevision())) {
                return Result.success(previous.afterRevision, previous.temporaryIds);
            }
            return Result.failure("conflict", "同一提案 ID 的重试内容或任务书状态不一致");
        }
        UndoneRecord previouslyUndone = LAST_UNDONE.get(player.getUUID());
        if (previouslyUndone != null && previouslyUndone.proposalId.equals(proposalId)) {
            return Result.failure("conflict", "该提案已经撤销，不能作为提交重试再次应用");
        }
        if (!security.bookRevision().equals(expectedRevision)) {
            return Result.failure("conflict", "任务书已发生变化，请重新生成提案");
        }

        JsonArray operations;
        try {
            JsonElement parsed = JsonParser.parseString(operationsJson);
            if (!parsed.isJsonArray()) {
                return Result.failure("failed", "提案操作必须是数组");
            }
            operations = parsed.getAsJsonArray();
        } catch (RuntimeException error) {
            return Result.failure("failed", "提案 JSON 无效");
        }
        if (operations.isEmpty() || operations.size() > MAX_OPERATIONS) {
            return Result.failure("failed", "提案操作数量超出范围");
        }

        // Parse the entire batch before touching the live quest book.
        try {
            for (int i = 0; i < operations.size(); i++) {
                try {
                    JsonElement element = operations.get(i);
                    if (!element.isJsonObject()) throw new IllegalArgumentException("提案操作必须是对象");
                    JsonObject operation = element.getAsJsonObject();
                    String kind = requiredString(operation, "kind", 64);
                    if (kind.endsWith("_raw") || operation.has("data_snbt")) {
                        requiredSnbt(operation, "data_snbt");
                    }
                } catch (Exception error) {
                    throw new IllegalArgumentException("第 " + (i + 1) + " 项：" + safe(error));
                }
            }
        } catch (Exception error) {
            return Result.failure("failed", "事务预检失败，任务书未修改：" + safe(error));
        }

        FriendlyByteBuf snapshot = new FriendlyByteBuf(Unpooled.buffer());
        Map<String, Long> temporaryIds = new LinkedHashMap<>();
        boolean mutationStarted = false;
        try {
            file.writeNetDataFull(snapshot);
            if (snapshot.writerIndex() > MAX_UNDO_BYTES) {
                return Result.failure("failed", "任务书快照过大，无法保证安全回滚");
            }
            byte[] undoBytes = new byte[snapshot.writerIndex()];
            snapshot.getBytes(0, undoBytes);
            mutationStarted = true;
            for (JsonElement element : operations) {
                if (!element.isJsonObject()) {
                    throw new IllegalArgumentException("提案操作必须是对象");
                }
                applyOne(file, element.getAsJsonObject(), temporaryIds);
                // Later operations may reference objects created earlier in this
                // batch. onCreated() attaches children but does not rebuild IDs.
                file.refreshIDMap();
            }
            file.refreshIDMap();
            file.clearCachedData();
            file.markDirty();
            file.saveNow();
            syncBookAndPermissions(file, player);
            String newRevision = FTBQ2001Revision.compute(file);
            LAST_UNDO.put(player.getUUID(), new UndoRecord(
                    proposalId, expectedRevision, newRevision, operationsJson,
                    undoBytes, Map.copyOf(temporaryIds)));
            LAST_UNDONE.remove(player.getUUID());
            return Result.success(newRevision, temporaryIds);
        } catch (Exception error) {
            if (!mutationStarted) return Result.failure("failed", "快照准备失败，任务书未修改：" + safe(error));
            try {
                snapshot.readerIndex(0);
                restoreSnapshot(file, snapshot);
                file.refreshIDMap();
                file.clearCachedData();
                file.markDirty();
                file.saveNow();
                syncBookAndPermissions(file, player);
            } catch (Exception rollbackError) {
                return Result.failure("failed", "写入失败且回滚失败："
                        + safe(error) + "；" + safe(rollbackError));
            }
            return Result.failure("failed", "写入已回滚：" + safe(error));
        } finally {
            snapshot.release();
        }
    }

    public static Result undo(ServerPlayer player, String proposalId,
                              String expectedCurrentRevision) {
        ServerQuestFile file = ServerQuestFile.INSTANCE;
        if (file == null) return Result.failure("failed", "FTB Quests 服务端任务书尚未加载");
        var security = FTBQ2001ServerSecurity.snapshot(player);
        if (!security.canEdit()) return Result.failure("failed", "服务器拒绝了 FTB Quests 编辑权限");
        UndoneRecord previous = LAST_UNDONE.get(player.getUUID());
        if (previous != null && previous.proposalId.equals(proposalId)) {
            if (previous.beforeUndoRevision.equals(expectedCurrentRevision)
                    && previous.afterUndoRevision.equals(security.bookRevision())) {
                return new Result(true, "undone", "已撤销上次服务器事务",
                        previous.afterUndoRevision, Map.of());
            }
            return Result.failure("conflict", "同一撤销请求的任务书状态不一致");
        }
        UndoRecord undo = LAST_UNDO.get(player.getUUID());
        if (undo == null || !undo.proposalId.equals(proposalId)) {
            return Result.failure("conflict", "没有可用于此提案的撤销快照");
        }
        if (!security.bookRevision().equals(expectedCurrentRevision)
                || !security.bookRevision().equals(undo.afterRevision)) {
            return Result.failure("conflict", "任务书在写入后又发生变化，不能安全撤销");
        }
        FriendlyByteBuf snapshot = new FriendlyByteBuf(Unpooled.wrappedBuffer(undo.snapshot));
        FriendlyByteBuf current = new FriendlyByteBuf(Unpooled.buffer());
        boolean restoreStarted = false;
        try {
            file.writeNetDataFull(current);
            if (current.writerIndex() > MAX_UNDO_BYTES) {
                return Result.failure("failed", "当前任务书快照过大，无法保证撤销安全");
            }
            restoreStarted = true;
            restoreSnapshot(file, snapshot);
            file.refreshIDMap();
            file.clearCachedData();
            file.markDirty();
            file.saveNow();
            syncBookAndPermissions(file, player);
            LAST_UNDO.remove(player.getUUID(), undo);
            String restoredRevision = FTBQ2001Revision.compute(file);
            LAST_UNDONE.put(player.getUUID(), new UndoneRecord(
                    proposalId, expectedCurrentRevision, restoredRevision));
            return new Result(true, "undone", "已撤销上次服务器事务",
                    restoredRevision, Map.of());
        } catch (Exception error) {
            if (!restoreStarted) return Result.failure("failed", "撤销快照准备失败，任务书未修改：" + safe(error));
            try {
                current.readerIndex(0);
                restoreSnapshot(file, current);
                file.refreshIDMap();
                file.clearCachedData();
                file.markDirty();
                file.saveNow();
                syncBookAndPermissions(file, player);
            } catch (Exception rollbackError) {
                return Result.failure("failed", "撤销失败且恢复当前状态失败："
                        + safe(error) + "；" + safe(rollbackError));
            }
            return Result.failure("failed", "撤销失败，当前状态已恢复：" + safe(error));
        } finally {
            snapshot.release();
            current.release();
        }
    }

    private static void syncBookAndPermissions(ServerQuestFile file, ServerPlayer player) {
        new SyncQuestsMessage(file).sendToAll(player.getServer());
        // Match FTBQ login: a replacement client file loses editorPermission.
        // TeamData alone does not restore this independent server-derived flag.
        for (ServerPlayer recipient : player.getServer().getPlayerList().getPlayers()) {
            new SyncEditorPermissionMessage(PermissionsHelper.hasEditorPermission(recipient, false))
                    .sendTo(recipient);
        }
    }

    private static void restoreSnapshot(ServerQuestFile file, FriendlyByteBuf snapshot) {
        // FTBQ readNetDataFull reuses defaultChapterGroup without clearing its
        // chapters: it is normally called on a NEW client file. On an existing
        // server file old chapters would be appended and consume snapshot bytes
        // twice. Do not deleteSelf(): that also deletes player progress.
        file.getDefaultChapterGroup().clearChapters();
        file.readNetDataFull(snapshot);
        if (snapshot.isReadable()) throw new IllegalStateException("任务书快照存在未读取数据");
    }

    private static void applyOne(ServerQuestFile file, JsonObject operation,
                                 Map<String, Long> temporaryIds) {
        String kind = requiredString(operation, "kind", 64);
        switch (kind) {
            case "update_book_raw" -> {
                rejectUnknown(operation, "kind", "data_snbt");
                file.readData(requiredSnbt(operation, "data_snbt"));
            }
            case "upsert_chapter_group_raw" -> {
                rejectUnknown(operation, "kind", "group_id", "data_snbt");
                long id = requiredId(operation, "group_id");
                CompoundTag data = requiredSnbt(operation, "data_snbt");
                ChapterGroup group = file.getChapterGroup(id);
                boolean created = group == null;
                if (group == null) {
                    group = (ChapterGroup) file.create(
                            id, QuestObjectType.CHAPTER_GROUP, 0L, new CompoundTag());
                    if (group == null) throw new IllegalArgumentException("无法创建章节组：" + id);
                }
                group.readData(data);
                if (created) group.onCreated();
                else group.editedFromGUIOnServer();
            }
            case "delete_chapter_group" -> {
                rejectUnknown(operation, "kind", "group_id");
                ChapterGroup group = file.getChapterGroup(requiredId(operation, "group_id"));
                if (group == null || group.isDefaultGroup()) {
                    throw new IllegalArgumentException("找不到可删除的章节组");
                }
                group.deleteSelf();
            }
            case "upsert_reward_table_raw" -> {
                rejectUnknown(operation, "kind", "reward_table_id", "data_snbt");
                long id = requiredId(operation, "reward_table_id");
                CompoundTag data = requiredSnbt(operation, "data_snbt");
                RewardTable table = file.getRewardTable(id);
                boolean created = table == null;
                if (table == null) {
                    table = (RewardTable) file.create(
                            id, QuestObjectType.REWARD_TABLE, 0L, new CompoundTag());
                    if (table == null) throw new IllegalArgumentException("无法创建奖励表：" + id);
                }
                table.readData(data);
                if (created) table.onCreated();
                else table.editedFromGUIOnServer();
            }
            case "delete_reward_table" -> {
                rejectUnknown(operation, "kind", "reward_table_id");
                RewardTable table = file.getRewardTable(requiredId(operation, "reward_table_id"));
                if (table == null) throw new IllegalArgumentException("找不到可删除的奖励表");
                table.deleteSelf();
            }
            case "upsert_chapter_raw" -> {
                rejectUnknown(operation, "kind", "chapter_id", "data_snbt");
                long id = requiredId(operation, "chapter_id");
                CompoundTag data = requiredSnbt(operation, "data_snbt");
                String groupCode = data.getString("group");
                ChapterGroup targetGroup = groupCode.isBlank() ? file.getDefaultChapterGroup()
                        : file.getChapterGroup(QuestObjectBase.parseCodeString(groupCode));
                if (targetGroup == null) throw new IllegalArgumentException("章节组不存在：" + groupCode);
                Chapter chapter = file.getChapter(id);
                boolean created = chapter == null;
                if (chapter == null) {
                    CompoundTag extra = new CompoundTag();
                    extra.putLong("group", targetGroup.getId());
                    chapter = (Chapter) file.create(id, QuestObjectType.CHAPTER, 0L, extra);
                    if (chapter == null) throw new IllegalArgumentException("无法创建章节：" + id);
                } else if (chapter.getGroup() != targetGroup) {
                    targetGroup.addChapter(chapter);
                }
                chapter.readData(data);
                if (created) chapter.onCreated();
                else chapter.editedFromGUIOnServer();
            }
            case "upsert_quest_raw" -> {
                rejectUnknown(operation, "kind", "quest_id", "chapter_id", "data_snbt");
                long id = requiredId(operation, "quest_id");
                Chapter chapter = requireChapter(file, operation, "chapter_id", temporaryIds);
                CompoundTag data = requiredSnbt(operation, "data_snbt");
                Quest quest = file.getQuest(id);
                boolean created = quest == null;
                if (quest == null) {
                    quest = (Quest) file.create(id, QuestObjectType.QUEST, chapter.getId(),
                            new CompoundTag());
                    if (quest == null) throw new IllegalArgumentException("无法创建任务：" + id);
                } else if (quest.getChapter() != chapter) {
                    quest.move(chapter, quest.getX(), quest.getY());
                }
                quest.readData(data);
                if (created) quest.onCreated();
                else quest.editedFromGUIOnServer();
            }
            case "upsert_quest_object_raw" -> {
                rejectUnknown(operation, "kind", "quest_id", "object_kind", "object_id",
                        "type_id", "data_snbt");
                Quest quest = requireQuest(file, operation, "quest_id", temporaryIds);
                String objectKind = requiredString(operation, "object_kind", 16);
                String typeId = requiredString(operation, "type_id", 256);
                long objectId = requiredId(operation, "object_id");
                CompoundTag data = requiredSnbt(operation, "data_snbt");
                QuestObjectBase object = file.getBase(objectId);
                QuestObjectType objectType;
                if ("task".equals(objectKind)) objectType = QuestObjectType.TASK;
                else if ("reward".equals(objectKind)) objectType = QuestObjectType.REWARD;
                else throw new IllegalArgumentException("object_kind 必须是 task 或 reward");
                if (object != null && object.getObjectType() != objectType) {
                    throw new IllegalArgumentException("任务对象 ID 类型冲突：" + operation.get("object_id"));
                }
                boolean created = object == null;
                if (object == null) {
                    CompoundTag extra = new CompoundTag();
                    extra.putString("type", typeId);
                    object = file.create(objectId, objectType, quest.getId(), extra);
                    if (object == null) throw new IllegalArgumentException("当前整合包不支持类型：" + typeId);
                }
                object.readData(data);
                if (created) object.onCreated();
                else object.editedFromGUIOnServer();
            }
            case "remove_quest_object" -> {
                rejectUnknown(operation, "kind", "object_id");
                QuestObjectBase object = file.getBase(requiredId(operation, "object_id"));
                if (!(object instanceof Task) && !(object instanceof Reward)) {
                    throw new IllegalArgumentException("找不到可删除的任务条件或奖励");
                }
                object.deleteSelf();
            }
            case "delete_quest" -> {
                rejectUnknown(operation, "kind", "quest_id");
                Quest quest = requireQuest(file, operation, "quest_id", temporaryIds);
                quest.deleteChildren();
                quest.deleteSelf();
            }
            case "delete_chapter" -> {
                rejectUnknown(operation, "kind", "chapter_id");
                Chapter chapter = requireChapter(file, operation, "chapter_id", temporaryIds);
                chapter.deleteChildren();
                chapter.deleteSelf();
            }
            case "create_chapter" -> {
                rejectUnknown(operation, "kind", "temp_id", "title", "subtitle", "icon");
                String temporary = uniqueTemporary(operation, temporaryIds);
                long id = file.newID();
                CompoundTag extra = new CompoundTag();
                extra.putLong("group", 0L);
                Chapter chapter = (Chapter) file.create(id, QuestObjectType.CHAPTER, 0L, extra);
                chapter.setRawTitle(requiredString(operation, "title", 4000));
                if (operation.has("subtitle")) {
                    chapter.getRawSubtitle().add(requiredString(operation, "subtitle", 4000));
                }
                applyIcon(chapter, optionalString(operation, "icon", 256));
                chapter.onCreated();
                temporaryIds.put(temporary, id);
            }
            case "create_quest" -> {
                rejectUnknown(operation, "kind", "temp_id", "chapter_id", "title",
                        "subtitle", "description", "icon", "x", "y");
                String temporary = uniqueTemporary(operation, temporaryIds);
                Chapter chapter = requireChapter(file, operation, "chapter_id", temporaryIds);
                long id = file.newID();
                Quest quest = (Quest) file.create(id, QuestObjectType.QUEST, chapter.getId(),
                        new CompoundTag());
                quest.setRawTitle(requiredString(operation, "title", 4000));
                quest.setRawSubtitle(optionalString(operation, "subtitle", 4000));
                quest.setX(requiredFinite(operation, "x"));
                quest.setY(requiredFinite(operation, "y"));
                if (operation.has("description")) {
                    replaceDescription(quest, operation.get("description"));
                }
                applyIcon(quest, optionalString(operation, "icon", 256));
                quest.onCreated();
                temporaryIds.put(temporary, id);
            }
            case "update_quest" -> {
                rejectUnknown(operation, "kind", "quest_id", "changes");
                Quest quest = requireQuest(file, operation, "quest_id", temporaryIds);
                JsonObject changes = requiredObject(operation, "changes");
                rejectUnknown(changes, "title", "subtitle", "description", "icon", "x", "y");
                if (changes.has("title")) quest.setRawTitle(requiredString(changes, "title", 4000));
                if (changes.has("subtitle")) quest.setRawSubtitle(requiredString(changes, "subtitle", 4000));
                if (changes.has("icon")) applyIcon(quest, optionalString(changes, "icon", 256));
                if (changes.has("x")) quest.setX(requiredFinite(changes, "x"));
                if (changes.has("y")) quest.setY(requiredFinite(changes, "y"));
                if (changes.has("description")) {
                    replaceDescription(quest, changes.get("description"));
                }
                quest.editedFromGUIOnServer();
            }
            case "add_dependency" -> {
                rejectUnknown(operation, "kind", "quest_id", "dependency_id");
                Quest quest = requireQuest(file, operation, "quest_id", temporaryIds);
                Quest dependency = requireQuest(file, operation, "dependency_id", temporaryIds);
                if (quest == dependency) {
                    throw new IllegalArgumentException("任务不能依赖自身");
                }
                quest.addDependency(dependency);
                if (!quest.verifyDependencies(true)) {
                    throw new IllegalArgumentException("依赖会形成无效关系");
                }
            }
            case "add_item_task" -> {
                rejectUnknown(operation, "kind", "quest_id", "item_id", "count");
                Quest quest = requireQuest(file, operation, "quest_id", temporaryIds);
                Item item = requireItem(operation);
                int count = requiredCount(operation);
                CompoundTag extra = new CompoundTag();
                extra.putString("type", "item");
                ItemTask task = (ItemTask) file.create(
                        file.newID(), QuestObjectType.TASK, quest.getId(), extra);
                task.setStackAndCount(new ItemStack(item), count);
                task.onCreated();
            }
            case "add_checkmark_task" -> {
                rejectUnknown(operation, "kind", "quest_id");
                Quest quest = requireQuest(file, operation, "quest_id", temporaryIds);
                CompoundTag extra = new CompoundTag();
                extra.putString("type", "checkmark");
                CheckmarkTask task = (CheckmarkTask) file.create(
                        file.newID(), QuestObjectType.TASK, quest.getId(), extra);
                task.onCreated();
            }
            case "add_xp_task" -> {
                rejectUnknown(operation, "kind", "quest_id", "amount");
                Quest quest = requireQuest(file, operation, "quest_id", temporaryIds);
                CompoundTag extra = new CompoundTag();
                extra.putString("type", "xp");
                XPTask task = (XPTask) file.create(
                        file.newID(), QuestObjectType.TASK, quest.getId(), extra);
                task.setValue(requiredPositiveLong(operation, "amount"));
                task.onCreated();
            }
            case "add_item_reward" -> {
                rejectUnknown(operation, "kind", "quest_id", "item_id", "count");
                Quest quest = requireQuest(file, operation, "quest_id", temporaryIds);
                Item item = requireItem(operation);
                int count = requiredCount(operation);
                CompoundTag extra = new CompoundTag();
                extra.putString("type", "item");
                ItemReward reward = (ItemReward) file.create(
                        file.newID(), QuestObjectType.REWARD, quest.getId(), extra);
                CompoundTag data = new CompoundTag();
                NBTUtils.write(data, "item", new ItemStack(item));
                data.putInt("count", count);
                reward.readData(data);
                reward.onCreated();
            }
            case "add_xp_reward", "add_xp_levels_reward" -> {
                rejectUnknown(operation, "kind", "quest_id", "amount");
                Quest quest = requireQuest(file, operation, "quest_id", temporaryIds);
                int amount = requiredPositiveInt(operation, "amount");
                boolean levels = kind.equals("add_xp_levels_reward");
                CompoundTag extra = new CompoundTag();
                extra.putString("type", levels ? "xp_levels" : "xp");
                QuestObjectBase reward = file.create(
                        file.newID(), QuestObjectType.REWARD, quest.getId(), extra);
                CompoundTag data = new CompoundTag();
                if (levels) {
                    data.putInt("xp_levels", amount);
                    ((XPLevelsReward) reward).readData(data);
                } else {
                    data.putInt("xp", amount);
                    ((XPReward) reward).readData(data);
                }
                reward.onCreated();
            }
            default -> throw new IllegalArgumentException("不支持的提案操作：" + kind);
        }
    }

    private static Quest requireQuest(ServerQuestFile file, JsonObject value, String key,
                                      Map<String, Long> temporaryIds) {
        long id = resolveId(requiredString(value, key, 256), temporaryIds);
        Quest quest = file.getQuest(id);
        if (quest == null) throw new IllegalArgumentException("找不到任务：" + value.get(key));
        return quest;
    }

    private static Chapter requireChapter(ServerQuestFile file, JsonObject value, String key,
                                          Map<String, Long> temporaryIds) {
        long id = resolveId(requiredString(value, key, 256), temporaryIds);
        Chapter chapter = file.getChapter(id);
        if (chapter == null) throw new IllegalArgumentException("找不到章节：" + value.get(key));
        return chapter;
    }

    private static long resolveId(String value, Map<String, Long> temporaryIds) {
        Long temporary = temporaryIds.get(value);
        if (temporary != null) return temporary;
        return QuestObjectBase.parseCodeString(value);
    }

    private static String uniqueTemporary(JsonObject value, Map<String, Long> temporaryIds) {
        String key = requiredString(value, "temp_id", 256);
        if (temporaryIds.containsKey(key)) throw new IllegalArgumentException("temp_id 重复：" + key);
        return key;
    }

    private static Item requireItem(JsonObject value) {
        ResourceLocation id = ResourceLocation.tryParse(requiredString(value, "item_id", 256));
        if (id == null || BuiltInRegistries.ITEM.getOptional(id).isEmpty()) {
            throw new IllegalArgumentException("物品 ID 不存在：" + value.get("item_id"));
        }
        return BuiltInRegistries.ITEM.get(id);
    }

    private static void applyIcon(QuestObjectBase object, String icon) {
        if (icon.isBlank()) {
            object.setRawIcon(ItemStack.EMPTY);
            return;
        }
        ResourceLocation id = ResourceLocation.tryParse(icon);
        if (id == null || BuiltInRegistries.ITEM.getOptional(id).isEmpty()) {
            throw new IllegalArgumentException("图标物品 ID 不存在：" + icon);
        }
        object.setRawIcon(new ItemStack(BuiltInRegistries.ITEM.get(id)));
    }

    private static int requiredCount(JsonObject value) {
        if (!value.has("count")) throw new IllegalArgumentException("缺少 count");
        int count = value.get("count").getAsInt();
        if (count < 1) throw new IllegalArgumentException("count 必须大于零");
        return count;
    }

    private static int requiredPositiveInt(JsonObject value, String key) {
        if (!value.has(key) || !value.get(key).isJsonPrimitive()) {
            throw new IllegalArgumentException("缺少 " + key);
        }
        int number = value.get(key).getAsInt();
        if (number < 1) throw new IllegalArgumentException(key + " 必须大于零");
        return number;
    }

    private static long requiredPositiveLong(JsonObject value, String key) {
        if (!value.has(key) || !value.get(key).isJsonPrimitive()) {
            throw new IllegalArgumentException("缺少 " + key);
        }
        long number = value.get(key).getAsLong();
        if (number < 1) throw new IllegalArgumentException(key + " 必须大于零");
        return number;
    }

    private static void replaceDescription(Quest quest, JsonElement value) {
        if (!value.isJsonArray() || value.getAsJsonArray().size() > 256) {
            throw new IllegalArgumentException("description 必须是最多 256 段的文本数组");
        }
        java.util.List<String> lines = new java.util.ArrayList<>();
        for (JsonElement element : value.getAsJsonArray()) {
            if (!element.isJsonPrimitive()) {
                throw new IllegalArgumentException("description 只能包含文本");
            }
            String line = element.getAsString();
            if (line.length() > 4000) throw new IllegalArgumentException("description 段落过长");
            lines.add(line);
        }
        quest.getRawDescription().clear();
        quest.getRawDescription().addAll(lines);
    }

    private static double requiredFinite(JsonObject value, String key) {
        if (!value.has(key)) throw new IllegalArgumentException("缺少 " + key);
        double number = value.get(key).getAsDouble();
        if (!Double.isFinite(number) || Math.abs(number) > 1_000_000D) {
            throw new IllegalArgumentException(key + " 超出范围");
        }
        return number;
    }

    private static JsonObject requiredObject(JsonObject value, String key) {
        if (!value.has(key) || !value.get(key).isJsonObject()) {
            throw new IllegalArgumentException(key + " 必须是对象");
        }
        return value.getAsJsonObject(key);
    }

    private static String requiredString(JsonObject value, String key, int limit) {
        String result = optionalString(value, key, limit);
        if (result.isBlank()) throw new IllegalArgumentException("缺少 " + key);
        return result;
    }

    private static String optionalString(JsonObject value, String key, int limit) {
        if (!value.has(key) || value.get(key).isJsonNull()) return "";
        if (!value.get(key).isJsonPrimitive()) throw new IllegalArgumentException(key + " 必须是文本");
        String result = value.get(key).getAsString().trim();
        if (result.length() > limit) throw new IllegalArgumentException(key + " 过长");
        return result;
    }

    private static long requiredId(JsonObject value, String key) {
        String text = requiredString(value, key, 32);
        if (!text.matches("(?i)[0-9a-f]{1,16}")) {
            throw new IllegalArgumentException(key + " 不是有效 FTB Quests ID");
        }
        return QuestObjectBase.parseCodeString(text);
    }

    private static CompoundTag requiredSnbt(JsonObject value, String key) {
        String text = requiredString(value, key, 1024 * 1024);
        try {
            return TagParser.parseTag(text);
        } catch (Exception error) {
            throw new IllegalArgumentException(key + " 不是有效 compound SNBT：" + safe(error));
        }
    }

    private static void rejectUnknown(JsonObject value, String... allowed) {
        java.util.Set<String> names = java.util.Set.of(allowed);
        for (String key : value.keySet()) {
            if (!names.contains(key)) throw new IllegalArgumentException("不支持的字段：" + key);
        }
    }

    private static String safe(Exception error) {
        String value = error.getMessage();
        return value == null || value.isBlank() ? error.getClass().getSimpleName() : value;
    }

    public record Result(boolean success, String status, String message,
                         String bookRevision, Map<String, Long> temporaryIds) {
        static Result success(String revision, Map<String, Long> ids) {
            return new Result(true, "applied", "修改已由游戏服务器提交",
                    revision, Map.copyOf(ids));
        }

        static Result failure(String status, String message) {
            return new Result(false, status, message, "", Map.of());
        }
    }

    private record UndoRecord(String proposalId, String beforeRevision, String afterRevision,
                              String operationsJson, byte[] snapshot,
                              Map<String, Long> temporaryIds) {
    }

    private record UndoneRecord(String proposalId, String beforeUndoRevision,
                                String afterUndoRevision) {
    }
}
