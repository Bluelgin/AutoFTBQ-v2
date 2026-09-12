package dev.autoftbq.agent.compat.ftbq.v2001;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicLong;

/** Evidence-bearing, paged client data. Unknown is never equivalent to unavailable. */
public final class GameDataCatalog {
    private static final AtomicLong GENERATION = new AtomicLong();
    public static void invalidate() { GENERATION.incrementAndGet(); }
    private static String text(JsonObject a, String key) {
        return a.has(key) ? a.get(key).getAsString() : "";
    }
    public static JsonObject query(JsonObject args) {
        try {
            return queryInternal(args);
        } catch (RuntimeException failure) {
            JsonObject result = new JsonObject();
            result.addProperty("schema_version", 1);
            result.addProperty("source", "minecraft_client_runtime");
            result.addProperty("status", "error");
            result.addProperty("message", "数据查询参数无效或当前数据无法读取，请检查工具参数后重试");
            return result;
        }
    }
    private static JsonObject queryInternal(JsonObject args) {
        JsonObject result = new JsonObject();
        String version = Integer.toHexString(System.identityHashCode(Minecraft.getInstance().level))
                + ":" + GENERATION.get();
        result.addProperty("schema_version", 1);
        result.addProperty("data_version", version);
        result.addProperty("source", "minecraft_client_runtime");
        result.addProperty("coverage", "partial");
        String expected = text(args, "data_version");
        if (!expected.isBlank() && !expected.equals(version)) {
            result.addProperty("status", "stale_version");
            result.addProperty("message", "数据已重载，请从第一页重新查询");
            return result;
        }
        String kind = text(args, "kind");
        if (kind.equals("capabilities")) {
            JsonArray supported = new JsonArray();
            for (String entry : new String[]{"registry_page", "item_evidence", "recipes", "server_resource:loot_tables", "server_resource:advancements"}) supported.add(entry);
            result.add("supported", supported);
            JsonArray unknown = new JsonArray();
            for (String entry : new String[]{"runtime_loot_overrides", "trades", "scripted_drops", "custom_machine_adapters", "boss_summoning"}) unknown.add(entry);
            result.add("not_covered", unknown);
            result.addProperty("status", "ok");
            return result;
        }
        if (Minecraft.getInstance().level == null) {
            result.addProperty("status", "unavailable");
            return result;
        }
        if (kind.equals("registry_page")) {
            Registry<?> registry = switch (text(args, "registry")) {
                case "item" -> BuiltInRegistries.ITEM;
                case "block" -> BuiltInRegistries.BLOCK;
                case "entity" -> BuiltInRegistries.ENTITY_TYPE;
                case "fluid" -> BuiltInRegistries.FLUID;
                case "recipe_type" -> BuiltInRegistries.RECIPE_TYPE;
                default -> null;
            };
            if (registry == null) {
                result.addProperty("status", "unsupported");
                return result;
            }
            int offset = Math.max(0, args.has("offset") ? args.get("offset").getAsInt() : 0);
            int limit = Math.max(1, Math.min(100, args.has("limit") ? args.get("limit").getAsInt() : 50));
            String needle = text(args, "query").toLowerCase(Locale.ROOT);
            String namespace = text(args, "namespace");
            var ids = registry.keySet().stream().filter(id ->
                (namespace.isBlank() || id.getNamespace().equals(namespace)) && id.toString().contains(needle)).sorted().toList();
            JsonArray entries = new JsonArray();
            for (int i = offset; i < Math.min(ids.size(), offset + limit); i++) {
                JsonObject entry = new JsonObject();
                entry.addProperty("id", ids.get(i).toString());
                entry.addProperty("registered", true);
                entries.add(entry);
            }
            result.add("entries", entries);
            result.addProperty("total", ids.size());
            result.addProperty("next_offset", Math.min(ids.size(), offset + entries.size()));
            result.addProperty("has_more", offset + entries.size() < ids.size());
            result.addProperty("coverage", "complete_for_selected_registry");
            result.addProperty("status", entries.isEmpty() ? "not_found" : "ok");
            return result;
        }
        if (kind.equals("item_evidence")) {
            ResourceLocation id = ResourceLocation.tryParse(text(args, "item_id"));
            boolean exists = id != null && BuiltInRegistries.ITEM.getOptional(id).isPresent();
            result.addProperty("registered", exists);
            result.addProperty("status", exists ? "ok" : "not_found");
            result.addProperty("availability", exists ? "unknown" : "invalid_id");
            result.addProperty("obtainability", "unknown");
            result.addProperty("development_complete", "unknown");
            if (!exists) return result;
            var item = BuiltInRegistries.ITEM.get(id);
            result.addProperty("id", id.toString());
            result.addProperty("name", item.getDescription().getString());
            JsonArray tags = new JsonArray();
            item.builtInRegistryHolder().tags().limit(256).forEach(tag -> tags.add(tag.location().toString()));
            result.add("tags", tags);
            result.addProperty("tags_truncated", item.builtInRegistryHolder().tags().count() > 256);
            try {
                var mc = Minecraft.getInstance();
                var model = mc.getItemRenderer().getItemModelShaper().getItemModel(item);
                result.addProperty("render_status", model.isCustomRenderer() ? "custom_renderer_unverified"
                        : model == mc.getModelManager().getMissingModel() ? "missing_model" : "base_model_present");
            } catch (RuntimeException error) {
                result.addProperty("render_status", "unknown");
            }
            result.addProperty("interpretation", "注册、基础模型和标签不是生存可获取或内容完成的证明；不要据此删除任务");
            return result;
        }
        if (kind.equals("recipes")) {
            result.add("data", FTBQ2001QueryExecutor.execute("search_recipes", args));
            result.addProperty("status", result.getAsJsonObject("data").has("error") ? "error" : "ok");
            return result;
        }
        result.addProperty("status", "unsupported");
        result.addProperty("message", "当前数据源没有覆盖此类信息，不能据此断定内容不存在");
        return result;
    }
}
