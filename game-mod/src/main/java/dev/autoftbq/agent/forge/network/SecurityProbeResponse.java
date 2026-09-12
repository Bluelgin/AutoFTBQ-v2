package dev.autoftbq.agent.forge.network;

import net.minecraft.network.FriendlyByteBuf;
import net.minecraftforge.network.NetworkEvent;

import java.util.function.Supplier;

public record SecurityProbeResponse(String nonce, boolean canEdit, String bookRevision) {
    static void encode(SecurityProbeResponse value, FriendlyByteBuf buffer) {
        buffer.writeUtf(value.nonce, 100);
        buffer.writeBoolean(value.canEdit);
        buffer.writeUtf(value.bookRevision, 128);
    }

    static SecurityProbeResponse decode(FriendlyByteBuf buffer) {
        return new SecurityProbeResponse(
                buffer.readUtf(100), buffer.readBoolean(), buffer.readUtf(128)
        );
    }

    static void handle(SecurityProbeResponse value, Supplier<NetworkEvent.Context> supplied) {
        NetworkEvent.Context context = supplied.get();
        context.enqueueWork(() -> ForgeAgentNetwork.completeProbe(value));
        context.setPacketHandled(true);
    }
}
