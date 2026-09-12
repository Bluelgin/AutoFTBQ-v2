package dev.autoftbq.agent.client;

import dev.ftb.mods.ftblibrary.ui.input.MouseButton;

/** Implemented by the version-specific FTB Quests screen mixin. */
public interface QuestScreenAgentHost {
    String autoftbq$getDraft();
    void autoftbq$setDraft(String value);
    void autoftbq$toggleAgentDock();

    boolean autoftbq$isAgentDockOpen();

    boolean autoftbq$routeAgentMousePressed(MouseButton button);

    boolean autoftbq$routeAgentMouseReleased(MouseButton button);

    boolean autoftbq$routeAgentMouseScrolled(double delta);

    boolean autoftbq$routeAgentMouseDragged(int button, double dragX, double dragY);
}
