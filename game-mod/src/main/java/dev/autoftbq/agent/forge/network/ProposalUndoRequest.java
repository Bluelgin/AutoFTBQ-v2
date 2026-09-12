package dev.autoftbq.agent.forge.network;

import dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ProposalExecutor;
import net.minecraft.network.FriendlyByteBuf;
import net.minecraft.server.level.ServerPlayer;
import net.minecraftforge.network.NetworkEvent;
import net.minecraftforge.network.PacketDistributor;

import java.util.function.Supplier;

public record ProposalUndoRequest(String requestId, String proposalId, String expectedBookRevision) {
    static void encode(ProposalUndoRequest value, FriendlyByteBuf buffer) {
        buffer.writeUtf(value.requestId, 100);
        buffer.writeUtf(value.proposalId, 100);
        buffer.writeUtf(value.expectedBookRevision, 128);
    }

    static ProposalUndoRequest decode(FriendlyByteBuf buffer) {
        return new ProposalUndoRequest(buffer.readUtf(100), buffer.readUtf(100), buffer.readUtf(128));
    }

    static void handle(ProposalUndoRequest value, Supplier<NetworkEvent.Context> supplied) {
        NetworkEvent.Context context = supplied.get();
        context.enqueueWork(() -> {
            ServerPlayer player = context.getSender();
            if (player == null) return;
            var result = FTBQ2001ProposalExecutor.undo(
                    player, value.proposalId, value.expectedBookRevision);
            ForgeAgentNetwork.CHANNEL.send(
                    PacketDistributor.PLAYER.with(() -> player),
                    new ProposalUndoResponse(
                            value.requestId, value.proposalId, result.success(), result.status(),
                            result.message(), result.bookRevision())
            );
        });
        context.setPacketHandled(true);
    }
}
