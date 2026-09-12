package dev.autoftbq.agent.forge.network;

import net.minecraft.network.FriendlyByteBuf;
import net.minecraftforge.network.NetworkEvent;

import java.util.function.Supplier;

public record ProposalApplyResponse(String requestId, String proposalId, boolean success, String status,
                                    String message, String bookRevision, String idMapJson) {
    static void encode(ProposalApplyResponse value, FriendlyByteBuf buffer) {
        buffer.writeUtf(value.requestId, 100);
        buffer.writeUtf(value.proposalId, 100);
        buffer.writeBoolean(value.success);
        buffer.writeUtf(value.status, 40);
        buffer.writeUtf(value.message, 2000);
        buffer.writeUtf(value.bookRevision, 128);
        buffer.writeUtf(value.idMapJson, 32_768);
    }

    static ProposalApplyResponse decode(FriendlyByteBuf buffer) {
        return new ProposalApplyResponse(
                buffer.readUtf(100), buffer.readUtf(100), buffer.readBoolean(), buffer.readUtf(40),
                buffer.readUtf(2000), buffer.readUtf(128), buffer.readUtf(32_768)
        );
    }

    static void handle(ProposalApplyResponse value, Supplier<NetworkEvent.Context> supplied) {
        NetworkEvent.Context context = supplied.get();
        context.enqueueWork(() -> ForgeAgentNetwork.completeApply(value));
        context.setPacketHandled(true);
    }
}
