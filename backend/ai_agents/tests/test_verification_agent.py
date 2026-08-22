# TARGET PATH: ai_agents/tests/test_verification_agent.py
"""
Agent-level tests for the Verification agent. These mock the Gemini call,
so they're not pure unit tests. Pure unit tests for build_prompt/
parse_response live separately in pure_unit_tests_verification_agent.py.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_agents.agents.verification_agent import (
    UniversityNameSuggestion,
    VerificationAgent,
)


class VerificationAgentRunTests(TestCase):

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_returns_university_name(self, mock_get_instance):
        # normal input
        mock_response = MagicMock()
        mock_response.text = '{"university_name": "Bangladesh University of Engineering and Technology"}'
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = (
            mock_response
        )
        mock_get_instance.return_value = mock_client_obj

        agent = VerificationAgent()
        result = agent.run({"domain": "buet.ac.bd"})

        self.assertEqual(
            result["university_name"],
            "Bangladesh University of Engineering and Technology",
        )

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_passes_temperature_and_schema_to_client(self, mock_get_instance):
        # behavior: confirms config actually reaches generate_content, not
        # just that the class attributes are set (that's AgentConfigTests
        # in the pure file, which only checks the attributes exist)
        mock_response = MagicMock()
        mock_response.text = '{"university_name": "Test University"}'
        mock_generate = MagicMock(return_value=mock_response)
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content = mock_generate
        mock_get_instance.return_value = mock_client_obj

        agent = VerificationAgent()
        agent.run({"domain": "test.edu"})

        _, call_kwargs = mock_generate.call_args
        self.assertEqual(call_kwargs["config"].temperature, 0)
        self.assertEqual(
            call_kwargs["config"].response_schema, UniversityNameSuggestion
        )

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_propagates_exception_on_api_failure(self, mock_get_instance):
        # unexpected input: Gemini call fails; the caller in
        # accounts/verification.py is responsible for the deterministic
        # fallback (leaving the raw domain text as the display name)
        mock_get_instance.side_effect = Exception("quota exceeded")

        agent = VerificationAgent()
        with self.assertRaises(Exception):
            agent.run({"domain": "buet.ac.bd"})
