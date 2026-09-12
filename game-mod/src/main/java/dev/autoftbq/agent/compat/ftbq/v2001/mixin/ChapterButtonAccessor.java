package dev.autoftbq.agent.compat.ftbq.v2001.mixin;

import dev.ftb.mods.ftbquests.quest.Chapter;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

@Mixin(targets = "dev.ftb.mods.ftbquests.client.gui.quests.ChapterPanel$ChapterButton", remap = false)
public interface ChapterButtonAccessor {
    @Accessor("chapter")
    Chapter autoftbq$getChapter();
}
