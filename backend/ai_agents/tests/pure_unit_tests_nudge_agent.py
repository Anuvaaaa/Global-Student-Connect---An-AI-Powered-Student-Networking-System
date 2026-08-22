# TARGET PATH: ai_agents/tests/pure_unit_tests_nudge_agent.py
"""
Pure unit tests for the Nudge agent — no DB, no Gemini, no mocking.
SimpleTestCase (not TestCase) since nothing here touches the database.
Mocked/agent-level tests live separately in test_nudge_agent.py.
"""

from django.test import SimpleTestCase

from ai_agents.agents.nudge_agent import NudgeAgent


class NudgeAgentBuildPromptTests(SimpleTestCase):
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


class NudgeAgentParseResponseTests(SimpleTestCase):
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
