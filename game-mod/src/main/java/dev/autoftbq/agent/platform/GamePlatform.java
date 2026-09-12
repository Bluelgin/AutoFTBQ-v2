package dev.autoftbq.agent.platform;

import java.util.Objects;

public final class GamePlatform {
    private static volatile GameServerGateway serverGateway;

    private GamePlatform() {
    }

    public static void installServerGateway(GameServerGateway value) {
        serverGateway = Objects.requireNonNull(value);
    }

    public static GameServerGateway serverGateway() {
        GameServerGateway value = serverGateway;
        if (value == null) throw new IllegalStateException("Game server gateway is not installed");
        return value;
    }
}
