package dev.autoftbq.agent;

import dev.autoftbq.agent.forge.network.ForgeAgentNetwork;
import dev.autoftbq.agent.forge.network.ForgeGameServerGateway;
import dev.autoftbq.agent.platform.GamePlatform;
import net.minecraftforge.fml.common.Mod;

@Mod(AutoFTBQAgentMod.MOD_ID)
public final class AutoFTBQAgentMod {
    public static final String MOD_ID = "autoftbq_agent";

    public AutoFTBQAgentMod() {
        // Platform-neutral features live outside this entry point.  Keeping the
        // Forge bootstrap tiny makes the later Fabric module straightforward.
        ForgeAgentNetwork.register();
        GamePlatform.installServerGateway(new ForgeGameServerGateway());
    }
}
