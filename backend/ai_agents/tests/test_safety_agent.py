# ai_agents/tests/test_safety_agent.py
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_agents.agents.safety_agent import SafetyAgent


class SafetyAgentTests(TestCase):
    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_returns_flagged_dict(self, mock_get_instance):
        mock_response = MagicMock()
        mock_response.text = (
            '{"flagged": true, "category": "harassment", "severity": "medium", '
            '"confidence": 0.87, "reasoning": "discouraging language directed at recipient"}'
        )
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = mock_response
        mock_get_instance.return_value = mock_client_obj

        result = SafetyAgent().run({"text": "some message"})

        self.assertTrue(result["flagged"])
        self.assertEqual(result["category"], "harassment")
        self.assertEqual(result["severity"], "medium")
        self.assertEqual(result["confidence"], 0.87)

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_returns_clear_dict(self, mock_get_instance):
        mock_response = MagicMock()
        mock_response.text = (
            '{"flagged": false, "category": "other", "severity": "low", '
            '"confidence": 0.1, "reasoning": "no issues detected"}'
        )
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = mock_response
        mock_get_instance.return_value = mock_client_obj

        result = SafetyAgent().run({"text": "hey, want to study together?"})

        self.assertFalse(result["flagged"])
