package dev.autoftbq.agent.forge;

import com.mojang.blaze3d.platform.InputConstants;
import dev.autoftbq.agent.AutoFTBQAgentMod;
import dev.autoftbq.agent.client.QuestScreenAgentHost;
import dev.ftb.mods.ftbquests.client.ClientQuestFile;
import dev.ftb.mods.ftbquests.client.gui.quests.QuestScreen;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.network.chat.Component;
import net.minecraftforge.api.distmarker.Dist;
import net.minecraftforge.client.event.RegisterKeyMappingsEvent;
import net.minecraftforge.event.TickEvent;
import net.minecraftforge.eventbus.api.SubscribeEvent;
import net.minecraftforge.fml.common.Mod;
import org.lwjgl.glfw.GLFW;

public final class AutoFTBQForgeClient {
    private static final KeyMapping OPEN_KEY = new KeyMapping(
            "key.autoftbq_agent.open",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_G,
            "key.categories.autoftbq_agent"
    );

    private AutoFTBQForgeClient() {
    }

    @Mod.EventBusSubscriber(modid = AutoFTBQAgentMod.MOD_ID, bus = Mod.EventBusSubscriber.Bus.MOD, value = Dist.CLIENT)
    public static final class ModEvents {
        @SubscribeEvent
        public static void registerKeys(RegisterKeyMappingsEvent event) {
            event.register(OPEN_KEY);
        }
    }

    @Mod.EventBusSubscriber(modid = AutoFTBQAgentMod.MOD_ID, bus = Mod.EventBusSubscriber.Bus.FORGE, value = Dist.CLIENT)
    public static final class ForgeEvents {
        @SubscribeEvent
        public static void recipesChanged(net.minecraftforge.client.event.RecipesUpdatedEvent event) {
            dev.autoftbq.agent.compat.ftbq.v2001.GameDataCatalog.invalidate();
        }

        @SubscribeEvent
        public static void tagsChanged(net.minecraftforge.event.TagsUpdatedEvent event) {
            dev.autoftbq.agent.compat.ftbq.v2001.GameDataCatalog.invalidate();
        }

        @SubscribeEvent
        public static void clientTick(TickEvent.ClientTickEvent event) {
            if (event.phase == TickEvent.Phase.END) {
                dev.autoftbq.agent.compat.ftbq.v2001.FTBQ2001ScreenSync.tick();
            }
            if (event.phase == TickEvent.Phase.END && OPEN_KEY.consumeClick()) {
                Minecraft minecraft = Minecraft.getInstance();
                if (minecraft.screen instanceof QuestScreenAgentHost host) {
                    host.autoftbq$toggleAgentDock();
                } else if (ClientQuestFile.exists()) {
                    QuestScreen screen = ClientQuestFile.openGui();
                    minecraft.execute(() -> ((QuestScreenAgentHost) screen)
                            .autoftbq$toggleAgentDock());
                } else if (minecraft.player != null) {
                    minecraft.player.displayClientMessage(Component.translatable(
                            "screen.autoftbq_agent.ftbq_required"), true);
                }
            }
        }
    }
}
