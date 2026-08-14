from unittest.mock import patch, MagicMock
from django.test import TestCase
from ai_agents.base import AIAgent

class DummyAgent(AIAgent):
    def build_prompt(self, payload):
        return f"echo: {payload['msg']}"
    def parse_response(self, raw_text):
        return self.parse_json(raw_text)

class AIAgentBaseTests(TestCase):
    def test_cannot_instantiate_abstract_class(self):
        with self.assertRaises(TypeError):
            AIAgent()

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_chains_prompt_call_parse(self, mock_get_instance):
        mock_response = MagicMock()
        mock_response.text = '{"ok": true}'
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = mock_response
        mock_get_instance.return_value = mock_client_obj

        result = DummyAgent().run({"msg": "hi"})
        self.assertEqual(result, {"ok": True})

    def test_parse_json_strips_markdown_fences(self):
        raw = '```json\n{"a": 1}\n```'
        self.assertEqual(AIAgent.parse_json(raw), {"a": 1})