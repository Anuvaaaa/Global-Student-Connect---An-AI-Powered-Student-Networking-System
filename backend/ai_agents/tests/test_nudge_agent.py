# TARGET PATH: ai_agents/tests/test_nudge_agent.py
"""
Agent-level tests for the Nudge agent — mocks the Gemini call, so these
are not pure unit tests. Pure unit tests for build_prompt/parse_response
live separately in pure_unit_tests_nudge_agent.py.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_agents.agents.nudge_agent import NudgeAgent


class NudgeAgentRunTests(TestCase):
    """Normal-input behavior: run() end-to-end through a mocked Gemini call."""

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_returns_nudge_text_for_badge(self, mock_get_instance):
        mock_response = MagicMock()
        mock_response.text = '{"nudge_text": "You are 85% toward Social Butterfly — a few more chats and it is yours."}'
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = mock_response
        mock_get_instance.return_value = mock_client_obj

        result = NudgeAgent().run({
            "progress_pct": 85,
            "badge_name": "Social Butterfly",
            "mission_name": None,
        })

        self.assertIn("nudge_text", result)
        self.assertIsInstance(result["nudge_text"], str)
        self.assertTrue(len(result["nudge_text"]) > 0)

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_returns_nudge_text_for_mission(self, mock_get_instance):
        mock_response = MagicMock()
        mock_response.text = '{"nudge_text": "One more message today finishes your daily mission!"}'
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = mock_response
        mock_get_instance.return_value = mock_client_obj

        result = NudgeAgent().run({
            "progress_pct": 90,
            "badge_name": None,
            "mission_name": "Send 3 messages",
        })

        self.assertIn("nudge_text", result)

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_strips_markdown_fences_from_response(self, mock_get_instance):
        # Gemini sometimes wraps JSON in ```json fences despite response_schema
        # being set — parse_json() is supposed to strip these.
        mock_response = MagicMock()
        mock_response.text = '```json\n{"nudge_text": "Almost there!"}\n```'
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = mock_response
        mock_get_instance.return_value = mock_client_obj

        result = NudgeAgent().run({
            "progress_pct": 80, "badge_name": "Global Explorer", "mission_name": None,
        })

        self.assertEqual(result["nudge_text"], "Almost there!")
