package dev.autoftbq.agent.compat.ftbq.v2001;

import dev.ftb.mods.ftbquests.quest.BaseQuestFile;
import io.netty.buffer.Unpooled;
import net.minecraft.network.FriendlyByteBuf;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/** Fingerprint of the exact definition payload FTB Quests synchronizes over the network. */
public final class FTBQ2001Revision {
    private FTBQ2001Revision() {
    }

    public static String compute(BaseQuestFile file) {
        if (file == null) {
            return "unavailable";
        }
        FriendlyByteBuf payload = new FriendlyByteBuf(Unpooled.buffer());
        try {
            file.writeNetDataFull(payload);
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = new byte[payload.writerIndex()];
            payload.getBytes(0, bytes);
            digest.update(bytes);
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        } finally {
            payload.release();
        }
    }
}
