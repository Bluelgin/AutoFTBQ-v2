package dev.autoftbq.agent.compat.ftbq.v2001;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import dev.ftb.mods.ftbquests.client.ClientQuestFile;
import dev.ftb.mods.ftbquests.quest.Quest;
import net.minecraft.client.Minecraft;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.Recipe;

import java.util.Collection;
import java.util.Locale;

/** Executes the small, explicit read-only query whitelist for FTBQ 2001. */
public final class FTBQ2001QueryExecutor {
    private FTBQ2001QueryExecutor() {
    }

    public static JsonObject execute(String name, JsonObject arguments) {
        return switch (name) {
            case "inspect_game_data" -> GameDataCatalog.query(arguments);
            case "get_selected_quest_details" -> selectedQuestDetails();
            case "search_registry" -> searchRegistry(arguments);
            case "search_registry_batch" -> searchRegistryBatch(arguments);
            case "validate_registry_ids" -> validateRegistryIds(arguments);
            case "search_recipes" -> searchRecipes(arguments);
            default -> error("不支持的只读游戏查询：" + name);
        };
    }

    private static JsonObject selectedQuestDetails() {
        if (!ClientQuestFile.exists()) {
            return error("FTB Quests 客户端任务书尚未加载");
        }
        Collection<Quest> selected = ClientQuestFile.INSTANCE.getQuestScreen()
                .map(screen -> screen.getSelectedQuests())
                .orElseGet(java.util.List::of);
        JsonArray quests = new JsonArray();
        selected.stream().limit(64).forEach(quest -> {
            JsonObject value = new JsonObject();
            value.addProperty("id", quest.getCodeString());
            value.addProperty("title", quest.getTitle().getString());
            value.addProperty("chapter_id", quest.getChapter().getCodeString());
            value.addProperty("chapter_title", quest.getChapter().getTitle().getString());
            value.addProperty("x", quest.getX());
            value.addProperty("y", quest.getY());
            CompoundTag questData = new CompoundTag();
            quest.writeData(questData);
            value.addProperty("data_snbt", bounded(questData.toString()));

            JsonArray dependencies = new JsonArray();
            quest.streamDependencies().limit(128)
                    .map(dependency -> dependency.getCodeString()).forEach(dependencies::add);
            value.add("dependencies", dependencies);

            JsonArray tasks = new JsonArray();
            quest.getTasks().stream().limit(128).forEach(task -> {
                JsonObject object = new JsonObject();
                object.addProperty("id", task.getCodeString());
                object.addProperty("type", task.getType().getTypeId().toString());
                object.addProperty("title", task.getTitle().getString());
                CompoundTag data = new CompoundTag();
                task.writeData(data);
                object.addProperty("data_snbt", bounded(data.toString()));
                tasks.add(object);
            });
            value.add("tasks", tasks);

            JsonArray rewards = new JsonArray();
            quest.getRewards().stream().limit(128).forEach(reward -> {
                JsonObject object = new JsonObject();
                object.addProperty("id", reward.getCodeString());
                object.addProperty("type", reward.getType().getTypeId().toString());
                object.addProperty("title", reward.getTitle().getString());
                CompoundTag data = new CompoundTag();
                reward.writeData(data);
                object.addProperty("data_snbt", bounded(data.toString()));
                rewards.add(object);
            });
            value.add("rewards", rewards);
            quests.add(value);
        });
        JsonObject result = new JsonObject();
        result.add("quests", quests);
        result.addProperty("selected_count", quests.size());
        return result;
    }

    private static JsonObject searchRecipes(JsonObject arguments) {
        ResourceLocation itemId = ResourceLocation.tryParse(stringArgument(arguments, "item_id").trim());
        String direction = stringArgument(arguments, "direction").toLowerCase(Locale.ROOT).trim();
        if (direction.isBlank()) {
            direction = "both";
        }
        if (itemId == null || BuiltInRegistries.ITEM.getOptional(itemId).isEmpty()) {
            return error("item_id 不是当前游戏中的有效物品 ID");
        }
        if (!direction.equals("input") && !direction.equals("output") && !direction.equals("both")) {
            return error("direction 仅支持 input、output 或 both");
        }
        int limit = arguments.has("limit") ? arguments.get("limit").getAsInt() : 20;
        limit = Math.max(1, Math.min(limit, 50));
        var level = Minecraft.getInstance().level;
        if (level == null) {
            return error("客户端世界尚未加载");
        }
        Item target = BuiltInRegistries.ITEM.get(itemId);
        JsonArray recipes = new JsonArray();
        var allRecipes = level.getRecipeManager().getRecipes().stream()
                .sorted(java.util.Comparator.comparing(recipe -> recipe.getId().toString())).toList();
        int offset = Math.max(0, arguments.has("offset") ? arguments.get("offset").getAsInt() : 0);
        int nextOffset = offset;
        int inspected = 0;
        int skipped = 0;
        for (int recipeIndex = offset; recipeIndex < allRecipes.size(); recipeIndex++) {
            if (recipes.size() >= limit || inspected >= 200) {
                break;
            }
            Recipe<?> recipe = allRecipes.get(recipeIndex);
            nextOffset = recipeIndex + 1;
            inspected++;
            try {
                ItemStack output = recipe.getResultItem(level.registryAccess());
                boolean produces = !output.isEmpty() && output.is(target);
                boolean consumes = recipe.getIngredients().stream()
                        .anyMatch(ingredient -> containsItem(ingredient, target));
                boolean include = direction.equals("both") ? produces || consumes
                        : direction.equals("output") ? produces : consumes;
                if (!include) {
                    continue;
                }
                JsonObject value = new JsonObject();
                value.addProperty("id", recipe.getId().toString());
                ResourceLocation typeId = BuiltInRegistries.RECIPE_TYPE.getKey(recipe.getType());
                value.addProperty("type", typeId == null ? "unknown" : typeId.toString());
                JsonObject outputValue = new JsonObject();
                outputValue.addProperty("id", BuiltInRegistries.ITEM.getKey(output.getItem()).toString());
                outputValue.addProperty("count", output.getCount());
                value.add("output", outputValue);
                JsonArray ingredients = new JsonArray();
                recipe.getIngredients().stream().limit(16).forEach(ingredient -> {
                    JsonArray alternatives = new JsonArray();
                    ItemStack[] stacks = ingredient.getItems();
                    for (int index = 0; index < Math.min(stacks.length, 32); index++) {
                        alternatives.add(BuiltInRegistries.ITEM.getKey(stacks[index].getItem()).toString());
                    }
                    ingredients.add(alternatives);
                });
                value.add("ingredients", ingredients);
                value.addProperty("matches_input", consumes);
                value.addProperty("matches_output", produces);
                recipes.add(value);
            } catch (RuntimeException ignored) {
                skipped++;
                // A modded recipe may rely on a custom client context; skip it without
                // breaking the rest of the bounded read-only query.
            }
        }
        JsonObject result = new JsonObject();
        result.addProperty("item_id", itemId.toString());
        result.addProperty("direction", direction);
        result.add("recipes", recipes);
        result.addProperty("result_count", recipes.size());
        result.addProperty("next_offset", Math.min(nextOffset, allRecipes.size()));
        result.addProperty("has_more", nextOffset < allRecipes.size());
        result.addProperty("inspected_count", inspected);
        result.addProperty("unreadable_count", skipped);
        result.addProperty("coverage", "client_recipe_manager_only");
        result.addProperty("ingredients_may_be_truncated", true);
        return result;
    }

    private static boolean containsItem(Ingredient ingredient, Item target) {
        for (ItemStack stack : ingredient.getItems()) {
            if (stack.is(target)) {
                return true;
            }
        }
        return false;
    }

    private static JsonObject searchRegistry(JsonObject arguments) {
        String registry = stringArgument(arguments, "registry").toLowerCase(Locale.ROOT);
        String query = stringArgument(arguments, "query").toLowerCase(Locale.ROOT).trim();
        int limit = arguments.has("limit") ? arguments.get("limit").getAsInt() : 20;
        limit = Math.max(1, Math.min(limit, 50));
        final int resultLimit = limit;
        if (query.isBlank()) {
            return error("query 不能为空");
        }
        JsonArray matches = new JsonArray();
        switch (registry) {
            case "item" -> BuiltInRegistries.ITEM.keySet().stream().sorted()
                    .forEach(id -> addMatch(matches, id,
                            BuiltInRegistries.ITEM.get(id).getDescription().getString(), query, resultLimit));
            case "block" -> BuiltInRegistries.BLOCK.keySet().stream().sorted()
                    .forEach(id -> addMatch(matches, id,
                            BuiltInRegistries.BLOCK.get(id).getName().getString(), query, resultLimit));
            case "entity" -> BuiltInRegistries.ENTITY_TYPE.keySet().stream().sorted()
                    .forEach(id -> addMatch(matches, id,
                            BuiltInRegistries.ENTITY_TYPE.get(id).getDescription().getString(), query, resultLimit));
            default -> {
                return error("registry 仅支持 item、block 或 entity");
            }
        }
        JsonObject result = new JsonObject();
        result.addProperty("registry", registry);
        result.addProperty("query", query);
        result.add("matches", matches);
        return result;
    }

    private static JsonObject searchRegistryBatch(JsonObject arguments) {
        if (arguments == null || !arguments.has("queries")
                || !arguments.get("queries").isJsonArray()) {
            return error("queries 必须是查询数组");
        }
        JsonArray queries = arguments.getAsJsonArray("queries");
        if (queries.isEmpty() || queries.size() > 64) {
            return error("queries 必须包含 1 到 64 项");
        }
        JsonArray results = new JsonArray();
        int count = 0;
        for (JsonElement element : queries) {
            if (count++ >= 64 || !element.isJsonObject()) continue;
            JsonObject query = element.getAsJsonObject().deepCopy();
            int limit = query.has("limit") ? query.get("limit").getAsInt() : 8;
            query.addProperty("limit", Math.max(1, Math.min(limit, 20)));
            JsonObject result = searchRegistry(query);
            result.addProperty("index", count - 1);
            results.add(result);
        }
        JsonObject response = new JsonObject();
        response.add("results", results);
        response.addProperty("query_count", results.size());
        return response;
    }

    private static JsonObject validateRegistryIds(JsonObject arguments) {
        String registry = stringArgument(arguments, "registry").toLowerCase(Locale.ROOT);
        if (arguments == null || !arguments.has("ids") || !arguments.get("ids").isJsonArray()) {
            return error("ids 必须是 ID 数组");
        }
        JsonArray ids = arguments.getAsJsonArray("ids");
        if (ids.isEmpty() || ids.size() > 64) {
            return error("ids 必须包含 1 到 64 项");
        }
        JsonArray results = new JsonArray();
        for (JsonElement element : ids) {
            if (!element.isJsonPrimitive()) continue;
            String raw = element.getAsString().trim();
            ResourceLocation id = ResourceLocation.tryParse(raw);
            boolean exists = id != null && switch (registry) {
                case "item" -> BuiltInRegistries.ITEM.getOptional(id).isPresent();
                case "block" -> BuiltInRegistries.BLOCK.getOptional(id).isPresent();
                case "entity" -> BuiltInRegistries.ENTITY_TYPE.getOptional(id).isPresent();
                default -> false;
            };
            JsonObject value = new JsonObject();
            value.addProperty("id", raw);
            value.addProperty("exists", exists);
            if (exists) {
                String name = switch (registry) {
                    case "item" -> BuiltInRegistries.ITEM.get(id).getDescription().getString();
                    case "block" -> BuiltInRegistries.BLOCK.get(id).getName().getString();
                    case "entity" -> BuiltInRegistries.ENTITY_TYPE.get(id).getDescription().getString();
                    default -> "";
                };
                value.addProperty("name", name);
            }
            results.add(value);
        }
        if (!registry.equals("item") && !registry.equals("block") && !registry.equals("entity")) {
            return error("registry 仅支持 item、block 或 entity");
        }
        JsonObject response = new JsonObject();
        response.addProperty("registry", registry);
        response.add("results", results);
        response.addProperty("validated_count", results.size());
        return response;
    }

    private static void addMatch(JsonArray matches, ResourceLocation id, String name,
                                 String query, int limit) {
        if (matches.size() >= limit) {
            return;
        }
        if (!id.toString().toLowerCase(Locale.ROOT).contains(query)
                && !name.toLowerCase(Locale.ROOT).contains(query)) {
            return;
        }
        JsonObject value = new JsonObject();
        value.addProperty("id", id.toString());
        value.addProperty("name", name);
        matches.add(value);
    }

    private static String stringArgument(JsonObject value, String key) {
        return value != null && value.has(key) ? value.get(key).getAsString() : "";
    }

    private static String bounded(String value) {
        return value.length() <= 12_000 ? value : value.substring(0, 12_000) + "…";
    }

    private static JsonObject error(String message) {
        JsonObject result = new JsonObject();
        result.addProperty("error", message);
        return result;
    }
}
