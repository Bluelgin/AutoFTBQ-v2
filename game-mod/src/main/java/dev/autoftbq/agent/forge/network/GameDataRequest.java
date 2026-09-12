package dev.autoftbq.agent.forge.network;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ServerSecurity;
import net.minecraft.network.FriendlyByteBuf;
import net.minecraft.resources.ResourceLocation;
import net.minecraftforge.network.NetworkEvent;
import net.minecraftforge.network.PacketDistributor;
import java.nio.charset.StandardCharsets;
import java.util.function.Supplier;

public record GameDataRequest(String nonce, String arguments) {
    static void encode(GameDataRequest v, FriendlyByteBuf b) { b.writeUtf(v.nonce, 100); b.writeUtf(v.arguments, 8192); }
    static GameDataRequest decode(FriendlyByteBuf b) { return new GameDataRequest(b.readUtf(100), b.readUtf(8192)); }
    static void handle(GameDataRequest value, Supplier<NetworkEvent.Context> supplied) {
        var context = supplied.get();
        context.enqueueWork(() -> {
            var player = context.getSender();
            if (player == null) return;
            JsonObject result = new JsonObject();
            result.addProperty("schema_version", 1);
            result.addProperty("source", "server_data_pack_resource");
            result.addProperty("coverage", "resource_only_runtime_script_overrides_unknown");
            try {
                if (!FTBQ2001ServerSecurity.snapshot(player).canEdit()) {
                    result.addProperty("status", "permission_denied");
                } else {
                    var args = JsonParser.parseString(value.arguments).getAsJsonObject();
                    String dataset = args.get("dataset").getAsString();
                    if ((dataset.equals("loot_tables") || dataset.equals("advancements")) && !args.has("id")) {
                        var entries = player.getServer().getResourceManager().listResources(dataset,
                            id -> id.getPath().endsWith(".json")).keySet().stream().sorted().toList();
                        String needle = args.has("query") ? args.get("query").getAsString() : "";
                        String namespace = args.has("namespace") ? args.get("namespace").getAsString() : "";
                        var filtered = entries.stream().filter(id -> id.toString().contains(needle)
                            && (namespace.isBlank() || id.getNamespace().equals(namespace))).toList();
                        int offset = Math.max(0, args.has("offset") ? args.get("offset").getAsInt() : 0);
                        int limit = Math.max(1, Math.min(100, args.has("limit") ? args.get("limit").getAsInt() : 50));
                        String version = Integer.toHexString(entries.hashCode());
                        result.addProperty("data_version", version);
                        if (args.has("data_version") && !version.equals(args.get("data_version").getAsString())) {
                            result.addProperty("status", "stale_version");
                        } else {
                            var ids = new com.google.gson.JsonArray();
                            for (int i = offset; i < Math.min(filtered.size(), offset + limit); i++) {
                                var id = filtered.get(i);
                                String path = id.getPath();
                                ids.add(id.getNamespace() + ":" + path.substring(dataset.length() + 1, path.length() - 5));
                            }
                            result.add("ids", ids);
                            result.addProperty("total", filtered.size());
                            result.addProperty("next_offset", Math.min(filtered.size(), offset + ids.size()));
                            result.addProperty("has_more", offset + ids.size() < filtered.size());
                            result.addProperty("status", ids.isEmpty() ? "not_found" : "ok");
                        }
                    } else {
                    String rawId = args.get("id").getAsString();
                    var id = ResourceLocation.tryParse(rawId);
                    if ((!dataset.equals("loot_tables") && !dataset.equals("advancements"))
                            || id == null || id.getPath().contains("..")) {
                        result.addProperty("status", "unsupported");
                    } else {
                        var resource = player.getServer().getResourceManager().getResource(
                                new ResourceLocation(id.getNamespace(), dataset + "/" + id.getPath() + ".json"));
                        result.addProperty("id", id.toString());
                        result.addProperty("dataset", dataset);
                        if (resource.isEmpty()) result.addProperty("status", "not_found");
                        else try (var input = resource.get().open()) {
                            byte[] bytes = input.readNBytes(64001);
                            if (bytes.length > 64000) result.addProperty("status", "too_large");
                            else {
                                String json = new String(bytes, StandardCharsets.UTF_8);
                                result.add("data", JsonParser.parseString(json));
                                result.addProperty("data_version", Integer.toHexString(json.hashCode()));
                                result.addProperty("status", "ok");
                            }
                        }
                    }
                    }
                }
            } catch (Exception error) {
                result.addProperty("status", "error");
                result.addProperty("message", "无法读取所请求的服务端资源");
            }
            ForgeAgentNetwork.CHANNEL.send(PacketDistributor.PLAYER.with(() -> player),
                    new GameDataResponse(value.nonce, result.toString()));
        });
        context.setPacketHandled(true);
    }
}
