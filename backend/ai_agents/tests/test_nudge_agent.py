# TARGET PATH: ai_agents/tests/test_nudge_agent.py
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


class NudgeAgentBuildPromptTests(TestCase):
    """build_prompt() input handling: normal, boundary, and unexpected input."""

    def setUp(self):
        self.agent = NudgeAgent()

    # --- normal input ---
    def test_includes_progress_and_badge_name(self):
        prompt = self.agent.build_prompt({
            "progress_pct": 72, "badge_name": "Global Explorer", "mission_name": None,
        })
        self.assertIn("72%", prompt)
        self.assertIn("Global Explorer", prompt)
        self.assertIn("badge", prompt)

    def test_includes_progress_and_mission_name(self):
        prompt = self.agent.build_prompt({
            "progress_pct": 40, "badge_name": None, "mission_name": "Send 3 messages",
        })
        self.assertIn("40%", prompt)
        self.assertIn("Send 3 messages", prompt)
        self.assertIn("mission", prompt)

    # --- boundary values ---
    def test_progress_pct_at_zero(self):
        prompt = self.agent.build_prompt({
            "progress_pct": 0, "badge_name": "First Friend", "mission_name": None,
        })
        self.assertIn("0%", prompt)

    def test_progress_pct_at_max(self):
        prompt = self.agent.build_prompt({
            "progress_pct": 100, "badge_name": "First Friend", "mission_name": None,
        })
        self.assertIn("100%", prompt)

    # --- unexpected input ---
    def test_raises_when_neither_badge_nor_mission_name_given(self):
        with self.assertRaises(ValueError):
            self.agent.build_prompt({"progress_pct": 80, "badge_name": None, "mission_name": None})

    def test_raises_when_payload_missing_progress_pct(self):
        with self.assertRaises(KeyError):
            self.agent.build_prompt({"badge_name": "First Friend", "mission_name": None})

    def test_badge_name_takes_precedence_when_both_given(self):
        # Documents actual behavior rather than leaving it implicit:
        # build_prompt() checks badge_name first, so a payload carrying
        # both (which callers should never construct, but nothing stops
        # a bad caller from doing so) silently prefers the badge.
        prompt = self.agent.build_prompt({
            "progress_pct": 50, "badge_name": "First Friend", "mission_name": "Send 3 messages",
        })
        self.assertIn("badge", prompt)
        self.assertIn("First Friend", prompt)


class NudgeAgentParseResponseTests(TestCase):
    """parse_response() input handling: normal and unexpected/malformed input."""

    def setUp(self):
        self.agent = NudgeAgent()

    def test_parses_valid_json(self):
        result = self.agent.parse_response('{"nudge_text": "Keep going!"}')
        self.assertEqual(result, {"nudge_text": "Keep going!"})

    def test_raises_on_malformed_json(self):
        with self.assertRaises(ValueError):
            self.agent.parse_response("not valid json at all")

    def test_raises_on_empty_string(self):
        with self.assertRaises(ValueError):
            self.agent.parse_response("")
