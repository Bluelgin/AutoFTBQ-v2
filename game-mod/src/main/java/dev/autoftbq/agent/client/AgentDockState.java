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
        // A full FTBQ sync temporarily replaces TeamData with a loading entry.
        // Keep an existing conversation visible; write permissions stay separate.
        return canEdit || open;
    }

    public static void setOpen(boolean value) {
        open = value;
    }

    public static boolean toggle() {
        open = !open;
        return open;
    }
}
