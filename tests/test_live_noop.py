import unittest
from copy import deepcopy

from autoftbq_v2.bridge.book_sync import diff_project_payload
from autoftbq_v2.ftb_store import FTBQuestStore


class LiveNoopTests(unittest.TestCase):
    def fixture(self):
        store = FTBQuestStore.create_new()
        payload = store._project_payload()
        for chapter in payload['chapters']:
            for quest in chapter['quests']:
                quest.pop('dependencies', None)
                quest.pop('description', None)
        return payload

    def test_read_save_does_not_add_empty_fields(self):
        base = self.fixture()
        desired = FTBQuestStore._from_project_payload(deepcopy(base))._project_payload()
        self.assertEqual(diff_project_payload(base, desired), [])

    def test_real_clear_is_not_ignored(self):
        base = self.fixture()
        quest = base['chapters'][0]['quests'][0]
        quest['description'] = ['Keep until explicitly cleared']
        store = FTBQuestStore._from_project_payload(deepcopy(base))
        store.project.chapters[0].quests[0].description = []
        operations = diff_project_payload(base, store._project_payload())
        self.assertEqual(len(operations), 1)
        self.assertIn('"description":[]', operations[0]['data_snbt'])
