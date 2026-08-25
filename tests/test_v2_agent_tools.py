import unittest

from autoftbq_v2.agent_core.tools import AgentToolRegistry


class AgentToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.source = [{
            "type": "function",
            "function": {"name": "inspect", "parameters": {"type": "object"}},
        }, {
            "type": "function",
            "function": {"name": "edit", "parameters": {"type": "object"}},
        }]
        self.registry = AgentToolRegistry(self.source, {"inspect"})

    def test_registry_classifies_read_and_write_tools(self):
        self.assertTrue(self.registry.contains("inspect"))
        self.assertTrue(self.registry.is_read_only("inspect"))
        self.assertTrue(self.registry.is_write("edit"))
        self.assertFalse(self.registry.is_write("invented"))

    def test_returned_schemas_cannot_mutate_the_catalog(self):
        schemas = self.registry.specs()
        schemas[0]["function"]["name"] = "changed"

        self.assertTrue(self.registry.contains("inspect"))
        self.assertEqual(self.registry.function_specs()[0]["name"], "inspect")


if __name__ == "__main__":
    unittest.main()
