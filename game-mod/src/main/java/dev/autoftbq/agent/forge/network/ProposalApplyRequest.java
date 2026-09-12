package dev.autoftbq.agent.forge.network;

import com.google.gson.Gson;
import dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ProposalExecutor;
import net.minecraft.network.FriendlyByteBuf;
import net.minecraft.server.level.ServerPlayer;
import net.minecraftforge.network.NetworkEvent;
import net.minecraftforge.network.PacketDistributor;

import java.util.function.Supplier;

public record ProposalApplyRequest(String requestId, String proposalId, String expectedBookRevision,
                                   String operationsJson) {
    private static final Gson GSON = new Gson();

    static void encode(ProposalApplyRequest value, FriendlyByteBuf buffer) {
        buffer.writeUtf(value.requestId, 100);
        buffer.writeUtf(value.proposalId, 100);
        buffer.writeUtf(value.expectedBookRevision, 128);
        buffer.writeUtf(value.operationsJson, 262_144);
    }

    static ProposalApplyRequest decode(FriendlyByteBuf buffer) {
        return new ProposalApplyRequest(
                buffer.readUtf(100), buffer.readUtf(100), buffer.readUtf(128),
                buffer.readUtf(262_144)
        );
    }

    static void handle(ProposalApplyRequest value, Supplier<NetworkEvent.Context> supplied) {
        NetworkEvent.Context context = supplied.get();
        context.enqueueWork(() -> {
            ServerPlayer player = context.getSender();
            if (player == null) return;
            var result = FTBQ2001ProposalExecutor.apply(
                    player, value.proposalId, value.expectedBookRevision, value.operationsJson);
            ForgeAgentNetwork.CHANNEL.send(
                    PacketDistributor.PLAYER.with(() -> player),
                    new ProposalApplyResponse(
                            value.requestId, value.proposalId, result.success(), result.status(), result.message(),
                            result.bookRevision(), GSON.toJson(result.temporaryIds()))
            );
        });
        context.setPacketHandled(true);
    }
}
