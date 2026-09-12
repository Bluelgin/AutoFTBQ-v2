package dev.autoftbq.agent.compat.ftbq.v2001;

import dev.ftb.mods.ftbquests.quest.ServerQuestFile;
import net.minecraft.server.level.ServerPlayer;

/** Server-authoritative FTBQ permission and definition revision snapshot. */
public final class FTBQ2001ServerSecurity {
    private FTBQ2001ServerSecurity() {
    }

    public static Snapshot snapshot(ServerPlayer player) {
        ServerQuestFile file = ServerQuestFile.INSTANCE;
        boolean canEdit = file != null
                && file.getOrCreateTeamData(player).getCanEdit(player);
        return new Snapshot(canEdit, FTBQ2001Revision.compute(file));
    }

    public record Snapshot(boolean canEdit, String bookRevision) {
    }
}
