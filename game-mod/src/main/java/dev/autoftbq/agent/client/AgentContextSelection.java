package dev.autoftbq.agent.client;

import java.util.LinkedHashSet;
import java.util.Set;

/** Explicit Agent-only selection, independent from FTBQ's editing selection. */
public final class AgentContextSelection {
    private static final Set<String> CHAPTER_IDS = new LinkedHashSet<>();
    private static final Set<String> QUEST_IDS = new LinkedHashSet<>();

    private AgentContextSelection() {
    }

    public static synchronized boolean toggleChapter(String id) {
        String value = normalize(id);
        if (value.isEmpty()) return false;
        if (!CHAPTER_IDS.remove(value)) CHAPTER_IDS.add(value);
        return CHAPTER_IDS.contains(value);
    }

    public static synchronized boolean toggleQuest(String id) {
        String value = normalize(id);
        if (value.isEmpty()) return false;
        if (!QUEST_IDS.remove(value)) QUEST_IDS.add(value);
        return QUEST_IDS.contains(value);
    }

    public static synchronized boolean containsChapter(String id) {
        return CHAPTER_IDS.contains(normalize(id));
    }

    public static synchronized boolean containsQuest(String id) {
        return QUEST_IDS.contains(normalize(id));
    }

    public static synchronized Set<String> chapterIds() {
        return Set.copyOf(CHAPTER_IDS);
    }

    public static synchronized Set<String> questIds() {
        return Set.copyOf(QUEST_IDS);
    }

    public static synchronized int chapterCount() {
        return CHAPTER_IDS.size();
    }

    public static synchronized int questCount() {
        return QUEST_IDS.size();
    }

    public static synchronized boolean isEmpty() {
        return CHAPTER_IDS.isEmpty() && QUEST_IDS.isEmpty();
    }

    public static synchronized void retain(Set<String> chapterIds, Set<String> questIds) {
        CHAPTER_IDS.retainAll(normalized(chapterIds));
        QUEST_IDS.retainAll(normalized(questIds));
    }

    public static synchronized void clear() {
        CHAPTER_IDS.clear();
        QUEST_IDS.clear();
    }

    private static Set<String> normalized(Set<String> values) {
        Set<String> result = new LinkedHashSet<>();
        for (String value : values) {
            String normalized = normalize(value);
            if (!normalized.isEmpty()) result.add(normalized);
        }
        return result;
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim().toUpperCase();
    }
}
