package dev.autoftbq.agent;

import net.minecraft.nbt.TagParser;

/** Runs the real Mojang parser, not Studio's permissive file parser. */
public final class StrictSnbtSmoke {
    public static void main(String[] args) throws Exception {
        var tag = TagParser.parseTag("{\"title\":\"测试\",\"tasks\":[{\"type\":\"kill\",\"entity\":\"minecraft:ender_dragon\"},{\"type\":\"advancement\"}],\"text\":\"a\nb\rc\t\\\"\\\\n\",\"tiny\":1e-20d,\"bytes\":[B;1b,-2b],\"longs\":[L;3L,4L]}");
        if (!tag.getString("text").equals("a\nb\rc\t\"\\n")) throw new AssertionError("String changed");
        if (tag.getList("tasks", 10).size() != 2) throw new AssertionError("Tasks missing");
        if (tag.getByteArray("bytes")[1] != -2) throw new AssertionError("Typed array changed");
        try {
            TagParser.parseTag("{title:\"测试\"\ntasks:[]}");
            throw new AssertionError("Old relaxed transport should be rejected");
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException expected) {
            System.out.println("Strict SNBT native parser smoke passed");
        }
    }
}
