# ai_agents/tests/test_safety_pipeline.py
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_agents.services.safety_pipeline import check_message


class SafetyPipelineTests(TestCase):
    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_clean_message_is_allowed(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {
            "flagged": False, "category": "other", "severity": "low",
            "confidence": 0.95, "reasoning": "no issues detected",
        }
        mock_get_agent.return_value = mock_agent

        result = check_message("Hey, are you free to study this weekend?")

        self.assertEqual(result["action"], "allow")
        self.assertEqual(result["stage"], "clear")

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_medium_severity_flag_is_queued_for_review(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {
            "flagged": True, "category": "harassment", "severity": "medium",
            "confidence": 0.95, "reasoning": "targeted personal disparagement of a peer",
        }
        mock_get_agent.return_value = mock_agent

        result = check_message("why do you even bother showing up, no one likes working with you")

        self.assertEqual(result["action"], "queue_human_review")
        self.assertEqual(result["stage"], "llm")
        self.assertEqual(result["category"], "harassment")
        self.assertEqual(result["severity"], "medium")

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_low_severity_flag_is_queued_not_blocked(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {
            "flagged": True, "category": "inappropriate_content", "severity": "low",
            "confidence": 0.6, "reasoning": "borderline phrasing, unclear intent",
        }
        mock_get_agent.return_value = mock_agent

        result = check_message("borderline message")

        self.assertEqual(result["action"], "queue_human_review")

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_high_severity_flag_is_auto_blocked(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {
            "flagged": True, "category": "harassment", "severity": "high",
            "confidence": 0.98, "reasoning": "direct targeted insults and exclusionary language",
        }
        mock_get_agent.return_value = mock_agent

        result = check_message("Nobody wants you here so just drop out idiot")

        self.assertEqual(result["action"], "auto_block")
        self.assertEqual(result["stage"], "llm")

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_retries_on_transient_failure_then_succeeds(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.side_effect = [
            Exception("timeout"),
            {
                "flagged": False, "category": "other", "severity": "low",
                "confidence": 0.9, "reasoning": "no issues detected",
            },
        ]
        mock_get_agent.return_value = mock_agent

        # No custom retry wrapper anymore (SDK handles its own retries),
        # so a raised exception here goes straight to the fail-open path.
        result = check_message("hello")

        self.assertEqual(result["action"], "allow")
        self.assertEqual(result["stage"], "error_fallback")
