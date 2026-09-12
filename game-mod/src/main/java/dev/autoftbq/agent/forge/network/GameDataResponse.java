package dev.autoftbq.agent.forge.network;

import net.minecraft.network.FriendlyByteBuf;
import net.minecraftforge.network.NetworkEvent;
import java.util.function.Supplier;

public record GameDataResponse(String nonce, String result) {
    static void encode(GameDataResponse v, FriendlyByteBuf b) { b.writeUtf(v.nonce, 100); b.writeUtf(v.result, 100000); }
    static GameDataResponse decode(FriendlyByteBuf b) { return new GameDataResponse(b.readUtf(100), b.readUtf(100000)); }
    static void handle(GameDataResponse v, Supplier<NetworkEvent.Context> supplied) {
        var context = supplied.get();
        context.enqueueWork(() -> ForgeAgentNetwork.completeData(v));
        context.setPacketHandled(true);
    }
}
