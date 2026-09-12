package dev.autoftbq.agent.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public record BridgeDiscovery(int protocolVersion, String host, int port, String token) {
    private static final Gson GSON = new Gson();

    public static BridgeDiscovery load() throws IOException {
        Path path = Path.of(System.getProperty("user.home"), ".autoftbq", "bridge.json");
        JsonObject value = GSON.fromJson(Files.readString(path, StandardCharsets.UTF_8), JsonObject.class);
        if (value == null) {
            throw new IOException("Studio bridge discovery file is empty");
        }
        int protocol = value.get("protocol_version").getAsInt();
        String host = value.get("host").getAsString();
        int port = value.get("port").getAsInt();
        String token = value.get("token").getAsString();
        if (protocol != 1 || !"127.0.0.1".equals(host) || port < 1 || port > 65535 || token.isBlank()) {
            throw new IOException("Studio bridge discovery file is incompatible");
        }
        return new BridgeDiscovery(protocol, host, port, token);
    }

    public String endpoint(String path) {
        return "http://" + host + ":" + port + path;
    }
}
