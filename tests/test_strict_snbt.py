import unittest

from snbt_parser import parse_snbt, to_snbt, to_strict_snbt


class StrictSnbtTests(unittest.TestCase):
    def test_compound_list_commas(self):
        value = {'title': '测试', 'tasks': [{'type': 'kill', 'entity': 'minecraft:ender_dragon'}, {'type': 'advancement'}]}
        result = to_strict_snbt(value)
        self.assertIn('},{', result)
        self.assertIn(',"tasks":', result)
        self.assertEqual(parse_snbt(result), value)
        self.assertNotIn('},{', to_snbt(value))

    def test_brigadier_escapes(self):
        value = {'text': 'a\nb\rc\t"\\n'}
        result = to_strict_snbt(value)
        self.assertIn('a\nb\rc\t', result)
        self.assertEqual(parse_snbt(result), value)

    def test_numeric_and_arrays(self):
        value = parse_snbt('{b:1b s:2s l:3L a:[B;1b,-2b] i:[I;1,2] z:[L;3L,4L]}')
        result = to_strict_snbt(value)
        self.assertIn('[B;1b,-2b]', result)
        self.assertIn('[L;3L,4L]', result)
        self.assertEqual(parse_snbt(result), value)
        self.assertEqual(to_strict_snbt(1e-20), '1e-20d')

    def test_unrepresentable_values_rejected(self):
        for value in [None, float('nan'), float('inf'), [1, 'x'], 2**40, {1: 'x'}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                to_strict_snbt(value)


if __name__ == '__main__':
    unittest.main()
