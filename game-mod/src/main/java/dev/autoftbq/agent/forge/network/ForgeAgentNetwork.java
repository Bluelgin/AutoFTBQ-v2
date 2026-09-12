package dev.autoftbq.agent.forge.network;

import dev.autoftbq.agent.AutoFTBQAgentMod;
import dev.autoftbq.agent.platform.ServerSecurityState;
import net.minecraft.resources.ResourceLocation;
import net.minecraftforge.network.NetworkDirection;
import net.minecraftforge.network.NetworkRegistry;
import net.minecraftforge.network.simple.SimpleChannel;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;

public final class ForgeAgentNetwork {
    private static final String VERSION = "3";
    private static final Map<String, CompletableFuture<String>> DATA = new ConcurrentHashMap<>();
    public static final SimpleChannel CHANNEL = NetworkRegistry.ChannelBuilder
            .named(new ResourceLocation(AutoFTBQAgentMod.MOD_ID, "main"))
            .networkProtocolVersion(() -> VERSION)
            .clientAcceptedVersions(VERSION::equals)
            .serverAcceptedVersions(VERSION::equals)
            .simpleChannel();
    private static final Map<String, CompletableFuture<ServerSecurityState>> PROBES =
            new ConcurrentHashMap<>();
    private static final Map<String, CompletableFuture<ProposalApplyResponse>> APPLICATIONS =
            new ConcurrentHashMap<>();
    private static final Map<String, CompletableFuture<ProposalUndoResponse>> UNDOS =
            new ConcurrentHashMap<>();
    private static boolean registered;

    private ForgeAgentNetwork() {
    }

    public static synchronized void register() {
        if (registered) {
            return;
        }
        registered = true;
        CHANNEL.messageBuilder(GameDataRequest.class, 6, NetworkDirection.PLAY_TO_SERVER)
                .encoder(GameDataRequest::encode).decoder(GameDataRequest::decode)
                .consumerMainThread(GameDataRequest::handle).add();
        CHANNEL.messageBuilder(GameDataResponse.class, 7, NetworkDirection.PLAY_TO_CLIENT)
                .encoder(GameDataResponse::encode).decoder(GameDataResponse::decode)
                .consumerMainThread(GameDataResponse::handle).add();
        CHANNEL.messageBuilder(SecurityProbeRequest.class, 0, NetworkDirection.PLAY_TO_SERVER)
                .encoder(SecurityProbeRequest::encode)
                .decoder(SecurityProbeRequest::decode)
                .consumerMainThread(SecurityProbeRequest::handle)
                .add();
        CHANNEL.messageBuilder(SecurityProbeResponse.class, 1, NetworkDirection.PLAY_TO_CLIENT)
                .encoder(SecurityProbeResponse::encode)
                .decoder(SecurityProbeResponse::decode)
                .consumerMainThread(SecurityProbeResponse::handle)
                .add();
        CHANNEL.messageBuilder(ProposalApplyRequest.class, 2, NetworkDirection.PLAY_TO_SERVER)
                .encoder(ProposalApplyRequest::encode)
                .decoder(ProposalApplyRequest::decode)
                .consumerMainThread(ProposalApplyRequest::handle)
                .add();
        CHANNEL.messageBuilder(ProposalApplyResponse.class, 3, NetworkDirection.PLAY_TO_CLIENT)
                .encoder(ProposalApplyResponse::encode)
                .decoder(ProposalApplyResponse::decode)
                .consumerMainThread(ProposalApplyResponse::handle)
                .add();
        CHANNEL.messageBuilder(ProposalUndoRequest.class, 4, NetworkDirection.PLAY_TO_SERVER)
                .encoder(ProposalUndoRequest::encode)
                .decoder(ProposalUndoRequest::decode)
                .consumerMainThread(ProposalUndoRequest::handle)
                .add();
        CHANNEL.messageBuilder(ProposalUndoResponse.class, 5, NetworkDirection.PLAY_TO_CLIENT)
                .encoder(ProposalUndoResponse::encode)
                .decoder(ProposalUndoResponse::decode)
                .consumerMainThread(ProposalUndoResponse::handle)
                .add();
    }

    public static CompletableFuture<ServerSecurityState> probeServer() {
        String nonce = UUID.randomUUID().toString();
        CompletableFuture<ServerSecurityState> future = new CompletableFuture<>();
        PROBES.put(nonce, future);
        CHANNEL.sendToServer(new SecurityProbeRequest(nonce));
        return future.orTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
                .whenComplete((ignored, error) -> PROBES.remove(nonce));
    }

    public static CompletableFuture<String> queryData(String arguments) {
        String nonce = UUID.randomUUID().toString();
        var future = new CompletableFuture<String>();
        DATA.put(nonce, future);
        CHANNEL.sendToServer(new GameDataRequest(nonce, arguments));
        return future.orTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
                .whenComplete((ignored, error) -> DATA.remove(nonce));
    }

    static void completeData(GameDataResponse response) {
        var future = DATA.get(response.nonce());
        if (future != null) future.complete(response.result());
    }

    static void completeProbe(SecurityProbeResponse response) {
        CompletableFuture<ServerSecurityState> future = PROBES.get(response.nonce());
        if (future != null) {
            future.complete(new ServerSecurityState(
                    response.canEdit(), response.bookRevision()
            ));
        }
    }

    public static CompletableFuture<ProposalApplyResponse> applyProposal(
            String proposalId, String expectedRevision, String operationsJson) {
        String requestId = UUID.randomUUID().toString();
        CompletableFuture<ProposalApplyResponse> future = new CompletableFuture<>();
        APPLICATIONS.put(requestId, future);
        CHANNEL.sendToServer(new ProposalApplyRequest(
                requestId, proposalId, expectedRevision, operationsJson));
        return future.orTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
                .whenComplete((ignored, error) -> APPLICATIONS.remove(requestId));
    }

    static void completeApply(ProposalApplyResponse response) {
        CompletableFuture<ProposalApplyResponse> future = APPLICATIONS.get(response.requestId());
        if (future != null) future.complete(response);
    }

    public static CompletableFuture<ProposalUndoResponse> undoProposal(
            String proposalId, String expectedRevision) {
        String requestId = UUID.randomUUID().toString();
        CompletableFuture<ProposalUndoResponse> future = new CompletableFuture<>();
        UNDOS.put(requestId, future);
        CHANNEL.sendToServer(new ProposalUndoRequest(requestId, proposalId, expectedRevision));
        return future.orTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
                .whenComplete((ignored, error) -> UNDOS.remove(requestId));
    }

    static void completeUndo(ProposalUndoResponse response) {
        CompletableFuture<ProposalUndoResponse> future = UNDOS.get(response.requestId());
        if (future != null) future.complete(response);
    }
}
