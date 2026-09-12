package dev.autoftbq.agent.forge.network;

import dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ServerSecurity;
import net.minecraft.network.FriendlyByteBuf;
import net.minecraft.server.level.ServerPlayer;
import net.minecraftforge.network.NetworkEvent;
import net.minecraftforge.network.PacketDistributor;

import java.util.function.Supplier;

public record SecurityProbeRequest(String nonce) {
    static void encode(SecurityProbeRequest value, FriendlyByteBuf buffer) {
        buffer.writeUtf(value.nonce, 100);
    }

    static SecurityProbeRequest decode(FriendlyByteBuf buffer) {
        return new SecurityProbeRequest(buffer.readUtf(100));
    }

    static void handle(SecurityProbeRequest value, Supplier<NetworkEvent.Context> supplied) {
        NetworkEvent.Context context = supplied.get();
        context.enqueueWork(() -> {
            ServerPlayer player = context.getSender();
            if (player == null) {
                return;
            }
            var snapshot = FTBQ2001ServerSecurity.snapshot(player);
            ForgeAgentNetwork.CHANNEL.send(
                    PacketDistributor.PLAYER.with(() -> player),
                    new SecurityProbeResponse(
                            value.nonce, snapshot.canEdit(), snapshot.bookRevision())
            );
        });
        context.setPacketHandled(true);
    }
}
