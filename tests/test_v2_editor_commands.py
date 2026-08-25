import unittest

from autoftbq_v2.editor.commands import EditorProjectCommands
from autoftbq_v2.ftb_store import FTBQuestStore


class EditorProjectCommandsTests(unittest.TestCase):
    def setUp(self):
        self.store = FTBQuestStore.create_new(with_starter=False)
        self.commands = EditorProjectCommands(lambda: self.store)
        self.chapter = self.store.create_chapter("开始")

    def test_provider_tracks_replaced_store(self):
        replacement = FTBQuestStore.create_new(with_starter=False)
        self.store = replacement

        chapter = self.commands.create_chapter()

        self.assertIs(replacement.chapter(chapter.id), chapter)

    def test_add_quest_uses_next_title_and_requested_position(self):
        self.store.add_quest(self.chapter.id, "已有任务")

        quest = self.commands.add_quest(self.chapter.id, 2.5, -1.25)

        self.assertEqual(quest.title, "新任务 2")
        self.assertEqual((quest.x, quest.y), (2.5, -1.25))
        self.assertEqual(quest.dependencies, [])

    def test_paste_quest_rekeys_and_can_drop_dependencies(self):
        source = self.store.add_quest(self.chapter.id, "来源")
        dependency = self.store.add_quest(self.chapter.id, "前置")
        self.store.connect(source.id, dependency.id)

        result = self.commands.paste_canvas_object(
            {"kind": "quest", "chapter_id": self.chapter.id, "id": source.id},
            self.chapter.id,
            4.0,
            3.0,
            with_dependencies=False,
        )

        copied = self.store.quest(result.object_id)[1]
        self.assertEqual(result.kind, "quest")
        self.assertNotEqual(copied.id, source.id)
        self.assertEqual(copied.dependencies, [])
        self.assertEqual((copied.x, copied.y), (4.0, 3.0))

    def test_paste_quest_as_link_keeps_linked_quest_id(self):
        source = self.store.add_quest(self.chapter.id, "来源")

        result = self.commands.paste_canvas_object(
            {"kind": "quest", "chapter_id": self.chapter.id, "id": source.id},
            self.chapter.id,
            1.0,
            2.0,
            as_link=True,
        )

        link = next(value for value in self.store.chapter_data(self.chapter.id)["quest_links"])
        self.assertEqual(result.kind, "link")
        self.assertEqual(link["linked_quest"], source.id)


if __name__ == "__main__":
    unittest.main()
