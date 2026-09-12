package dev.autoftbq.agent.forge.network;

import dev.autoftbq.agent.platform.GameServerGateway;
import dev.autoftbq.agent.platform.ProposalApplicationResult;
import dev.autoftbq.agent.platform.ProposalUndoResult;
import dev.autoftbq.agent.platform.ServerSecurityState;

import java.util.concurrent.CompletableFuture;

public final class ForgeGameServerGateway implements GameServerGateway {
    @Override
    public CompletableFuture<ServerSecurityState> probeServer() {
        return ForgeAgentNetwork.probeServer();
    }

    @Override
    public CompletableFuture<ProposalApplicationResult> applyProposal(
            String proposalId, String expectedRevision, String operationsJson) {
        return ForgeAgentNetwork.applyProposal(proposalId, expectedRevision, operationsJson)
                .thenApply(value -> new ProposalApplicationResult(
                        value.success(), value.status(), value.message(),
                        value.bookRevision(), value.idMapJson()));
    }

    @Override
    public CompletableFuture<ProposalUndoResult> undoProposal(
            String proposalId, String expectedRevision) {
        return ForgeAgentNetwork.undoProposal(proposalId, expectedRevision)
                .thenApply(value -> new ProposalUndoResult(
                        value.success(), value.status(), value.message(), value.bookRevision()));
    }
}
