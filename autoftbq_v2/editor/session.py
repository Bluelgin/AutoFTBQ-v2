"""UI-independent selection and Agent-scope state for the quest editor."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EditorSessionState:
    current_chapter_id: str = ""
    current_quest_id: str = ""
    agent_chapter_ids: set[str] = field(default_factory=set)
    agent_quest_ids: set[str] = field(default_factory=set)

    def prune_agent_context(self, store) -> tuple[set[str], set[str]]:
        chapters = {chapter.id for chapter in store.project.chapters}
        quests = {quest.id for chapter in store.project.chapters for quest in chapter.quests}
        self.agent_chapter_ids.intersection_update(chapters)
        self.agent_quest_ids.intersection_update(quests)
        return self.agent_chapter_ids, self.agent_quest_ids

    def reconcile_selection(self, store) -> tuple[str, str]:
        chapter_ids = [chapter.id for chapter in store.project.chapters]
        if self.current_chapter_id not in chapter_ids:
            self.current_chapter_id = chapter_ids[0] if chapter_ids else ""
        chapter = store.chapter(self.current_chapter_id)
        quest_ids = [quest.id for quest in chapter.quests] if chapter else []
        if self.current_quest_id not in quest_ids:
            self.current_quest_id = quest_ids[0] if quest_ids else ""
        self.prune_agent_context(store)
        return self.current_chapter_id, self.current_quest_id

    def select_chapter(self, store, chapter_id: str) -> bool:
        chapter = store.chapter(str(chapter_id or ""))
        if chapter is None:
            return False
        self.current_chapter_id = chapter.id
        self.current_quest_id = chapter.quests[0].id if chapter.quests else ""
        return True

    def select_quest(self, store, quest_id: str) -> bool:
        found = store.quest(str(quest_id or ""))
        if found is None:
            return False
        self.current_chapter_id = found[0].id
        self.current_quest_id = found[1].id
        return True

    def toggle_agent_chapter(self, store, chapter_id: str) -> bool:
        chapter = store.chapter(str(chapter_id or ""))
        if chapter is None:
            return False
        if chapter.id in self.agent_chapter_ids:
            self.agent_chapter_ids.remove(chapter.id)
        else:
            self.agent_chapter_ids.add(chapter.id)
            self.agent_quest_ids.difference_update(quest.id for quest in chapter.quests)
        return True

    def toggle_agent_quest(self, store, quest_id: str) -> bool:
        found = store.quest(str(quest_id or ""))
        if found is None:
            return False
        chapter, quest = found
        if quest.id in self.agent_quest_ids:
            self.agent_quest_ids.remove(quest.id)
        else:
            self.agent_chapter_ids.discard(chapter.id)
            self.agent_quest_ids.add(quest.id)
        return True

    def clear_agent_context(self) -> None:
        self.agent_chapter_ids.clear()
        self.agent_quest_ids.clear()

    def clear_selection(self) -> None:
        self.current_chapter_id = ""
        self.current_quest_id = ""
