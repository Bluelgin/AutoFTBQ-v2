import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage
from autoftbq_v2.bridge.sketch import validate_sketch, enforce_new_chapter_only
from autoftbq_v2.bridge.protocol import ProtocolError
from autoftbq_v2.bridge.live_agent import LiveProjectAgent
from autoftbq_v2.agent import ProjectAgent
from ollama_adapter import OllamaClient


class SketchTests(unittest.TestCase):
    def sketch(self):
        image = QImage(128, 128, QImage.Format.Format_RGB32)
        image.fill(0xFFFFFFFF)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.assertTrue(image.save(buffer, 'PNG'))
        return {'mode': 'shape', 'image_data_url': 'data:image/png;base64,' + base64.b64encode(bytes(data)).decode()}

    def test_validation(self):
        value = self.sketch()
        self.assertEqual(validate_sketch(value), value)
        self.assertIsNone(validate_sketch(None))
        for change in ({'mode': 'other'}, {'image_data_url': 'https://example.com/x.png'},
                       {'image_data_url': 'data:image/png;base64,bad'}, {'extra': True}):
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                validate_sketch(value | change)

    def test_scope(self):
        base = {'chapters': [{'id': 'OLD', 'quests': [{'id': 'Q', 'tasks': [{'id': 'T'}], 'rewards': []}]}]}
        create = {'kind': 'upsert_chapter_raw', 'chapter_id': 'NEW'}
        quest = {'kind': 'upsert_quest_raw', 'chapter_id': 'NEW', 'quest_id': 'NQ'}
        self.assertEqual(enforce_new_chapter_only(base, [create, quest], set()), {'NEW'})
        for ops in ([create | {'chapter_id': 'OLD'}], [create, create | {'chapter_id': 'SECOND'}],
                    [create, quest | {'quest_id': 'Q'}], [create, quest, {'kind': 'upsert_quest_object_raw', 'quest_id': 'NQ', 'object_id': 'T'}],
                    [{'kind': 'delete_quest', 'quest_id': 'Q'}]):
            with self.subTest(ops=ops), self.assertRaises(ProtocolError):
                enforce_new_chapter_only(base, ops, set())
        self.assertEqual(enforce_new_chapter_only(base, [quest], {'NEW'}), {'NEW'})

    def test_image_attached_each_model_invocation(self):
        agent = object.__new__(LiveProjectAgent)
        agent.live_task = SimpleNamespace(record=SimpleNamespace(layout_sketch=self.sketch(), prompt='环形'))
        messages = [{'role': 'user', 'content': '生成'}]
        with patch.object(ProjectAgent, '_invoke_model', return_value='ok') as invoke:
            for _ in range(2):
                agent._invoke_model(messages, 12)
                content = invoke.call_args.args[0][-1]['content']
                self.assertEqual(content[-1]['image_url']['url'], agent.live_task.record.layout_sketch['image_data_url'])
        self.assertEqual(len(messages), 1)

    def test_ollama_does_not_drop_image_on_followup(self):
        with patch('ollama_adapter.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'response': 'ok', 'done': True}
            OllamaClient().chat([{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': self.sketch()['image_data_url']}}]},
                {'role': 'user', 'content': '继续'}])
            self.assertTrue(post.call_args.kwargs['json']['images'])
            self.assertEqual(post.call_args.kwargs['json']['prompt'], '继续')
