package dev.autoftbq.agent.platform;

import java.util.concurrent.CompletableFuture;

/** Loader-neutral client facade for server-authoritative operations. */
public interface GameServerGateway {
    CompletableFuture<ServerSecurityState> probeServer();

    CompletableFuture<ProposalApplicationResult> applyProposal(
            String proposalId, String expectedRevision, String operationsJson);

    CompletableFuture<ProposalUndoResult> undoProposal(
            String proposalId, String expectedRevision);
}
