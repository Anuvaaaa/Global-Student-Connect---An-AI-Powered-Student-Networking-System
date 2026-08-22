# TARGET PATH: ai_agents/tests/test_platform_assistant_agent.py
"""
Agent-level tests for the Platform Assistant agent. These mock the Gemini
call, so they're not pure unit tests. Pure unit tests for format_history/
get_fallback_message/build_prompt/parse_response live separately in
pure_unit_tests_platform_assistant_agent.py.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_agents.agents.platform_assistant_agent import PlatformAssistantAgent


class PlatformAssistantAgentRunTests(TestCase):

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_returns_in_scope_answer(self, mock_get_instance):
        # normal input / behavior: on-topic question returns in_scope True
        mock_response = MagicMock()
        mock_response.text = (
            '{"answer": "Groups need 40% interest overlap.", "in_scope": true}'
        )
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = (
            mock_response
        )
        mock_get_instance.return_value = mock_client_obj

        agent = PlatformAssistantAgent()
        result = agent.run({"question": "How does matching work?", "history": []})

        self.assertTrue(result["in_scope"])
        self.assertIn("40%", result["answer"])

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_returns_out_of_scope_refusal(self, mock_get_instance):
        # negative input / behavior: off-topic request gets refused, not answered
        mock_response = MagicMock()
        mock_response.text = (
            '{"answer": "I can only help with GSC-related questions.", '
            '"in_scope": false}'
        )
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = (
            mock_response
        )
        mock_get_instance.return_value = mock_client_obj

        agent = PlatformAssistantAgent()
        result = agent.run({"question": "Write my essay for me.", "history": []})

        self.assertFalse(result["in_scope"])

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_propagates_exception_on_api_failure(self, mock_get_instance):
        # unexpected input: the Gemini call itself throws (quota/timeout)
        # run() does not swallow this — the caller (ask_assistant view) is
        # the one responsible for catching it and showing the fallback
        # message, so this test only confirms the exception isn't hidden.
        mock_get_instance.side_effect = Exception("quota exceeded")

        agent = PlatformAssistantAgent()
        with self.assertRaises(Exception):
            agent.run({"question": "How do groups work?", "history": []})
