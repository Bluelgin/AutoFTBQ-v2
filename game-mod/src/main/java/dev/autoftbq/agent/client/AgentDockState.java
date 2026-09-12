package dev.autoftbq.agent.client;

/** Session-local dock state survives FTBQ screen reconstruction after a full sync. */
public final class AgentDockState {
    private static volatile boolean open;

    private AgentDockState() {
    }

    public static boolean isOpen() {
        return open;
    }

    public static boolean shouldAttach(boolean canEdit) {
        // Widget construction must not depend on editor permission. FTBQ restores
        // editorPermission asynchronously after a full client-file sync, so gating
        // addWidgets() on canEdit can permanently hide the Agent entry for that screen.
        // Actual writes and opening a closed dock remain permission-gated elsewhere.
        return true;
    }

    public static void setOpen(boolean value) {
        open = value;
    }

    public static boolean toggle() {
        open = !open;
        return open;
    }
}
