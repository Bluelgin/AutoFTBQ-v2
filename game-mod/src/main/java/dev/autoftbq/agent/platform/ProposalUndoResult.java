package dev.autoftbq.agent.platform;

public record ProposalUndoResult(boolean success, String status, String message,
                                 String bookRevision) {
}
