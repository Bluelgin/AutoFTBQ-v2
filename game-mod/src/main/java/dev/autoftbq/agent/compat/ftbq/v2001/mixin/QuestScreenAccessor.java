package dev.autoftbq.agent.compat.ftbq.v2001.mixin;

import dev.ftb.mods.ftbquests.client.gui.quests.QuestScreen;
import dev.ftb.mods.ftbquests.quest.Chapter;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

/** Version-scoped read-only access to the chapter currently displayed by FTBQ. */
@Mixin(value = QuestScreen.class, remap = false)
public interface QuestScreenAccessor {
    @Accessor("selectedChapter")
    Chapter autoftbq$getSelectedChapter();
}
