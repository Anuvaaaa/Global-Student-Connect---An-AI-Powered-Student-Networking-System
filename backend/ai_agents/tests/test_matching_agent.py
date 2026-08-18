# TARGET PATH: ai_agents/tests/test_matching_agent.py
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_agents.agents.matching_agent import MatchingAgent


class MatchingAgentRunTests(TestCase):
    """Normal input: run() end-to-end through a mocked Gemini call."""

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_returns_score_and_reasoning(self, mock_get_instance):
        mock_response = MagicMock()
        mock_response.text = '{"score": 82, "reasoning": "Both enjoy music and travel."}'
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = mock_response
        mock_get_instance.return_value = mock_client_obj

        result = MatchingAgent().run({
            "user_a_interests": ["Music", "Travel"],
            "user_b_interests": ["Music", "Gaming"],
            "user_a_country": "Bangladesh",
            "user_b_country": "India",
        })

        self.assertIn("score", result)
        self.assertIn("reasoning", result)
        self.assertEqual(result["score"], 82)

    @patch("ai_agents.client.GeminiClient.get_instance")
    def test_run_strips_markdown_fences_from_response(self, mock_get_instance):
        # Gemini sometimes wraps JSON in ```json fences despite response_schema
        # being set — parse_json() is supposed to strip these.
        mock_response = MagicMock()
        mock_response.text = '```json\n{"score": 70, "reasoning": "Some overlap."}\n```'
        mock_client_obj = MagicMock()
        mock_client_obj.get_client.return_value.models.generate_content.return_value = mock_response
        mock_get_instance.return_value = mock_client_obj

        result = MatchingAgent().run({
            "user_a_interests": ["Coding"], "user_b_interests": ["Cooking"],
            "user_a_country": "Nepal", "user_b_country": "Nepal",
        })

        self.assertEqual(result["score"], 70)


class MatchingAgentBuildPromptTests(TestCase):
    """build_prompt() input handling: normal, category, boundary, and unexpected input."""

    def setUp(self):
        self.agent = MatchingAgent()

    # --- normal input ---
    def test_includes_both_interest_lists_and_countries(self):
        prompt = self.agent.build_prompt({
            "user_a_interests": ["Music", "Travel"],
            "user_b_interests": ["Music", "Gaming"],
            "user_a_country": "Bangladesh",
            "user_b_country": "India",
        })
        self.assertIn("Music, Travel", prompt)
        self.assertIn("Music, Gaming", prompt)
        self.assertIn("Bangladesh", prompt)
        self.assertIn("India", prompt)

    def test_computes_shared_interests_line(self):
        prompt = self.agent.build_prompt({
            "user_a_interests": ["Music", "Travel", "Coding"],
            "user_b_interests": ["Coding", "Music"],
            "user_a_country": "Bangladesh", "user_b_country": "Bangladesh",
        })
        self.assertIn("Shared interests: Coding, Music", prompt)

    # --- category: positive vs negative overlap ---
    def test_no_shared_interests_states_none(self):
        prompt = self.agent.build_prompt({
            "user_a_interests": ["Music"], "user_b_interests": ["Cricket"],
            "user_a_country": "Nepal", "user_b_country": "Kenya",
        })
        self.assertIn("Shared interests: none", prompt)

    def test_fully_overlapping_interests_lists_all_as_shared(self):
        prompt = self.agent.build_prompt({
            "user_a_interests": ["Music", "Travel"], "user_b_interests": ["Music", "Travel"],
            "user_a_country": "Nepal", "user_b_country": "Nepal",
        })
        self.assertIn("Shared interests: Music, Travel", prompt)

    # --- boundary values: empty interest lists ---
    def test_empty_interest_lists_render_as_none_listed(self):
        prompt = self.agent.build_prompt({
            "user_a_interests": [], "user_b_interests": [],
            "user_a_country": "Nepal", "user_b_country": "Nepal",
        })
        self.assertIn("Student A interests: none listed", prompt)
        self.assertIn("Student B interests: none listed", prompt)

    def test_one_empty_one_populated_interest_list(self):
        prompt = self.agent.build_prompt({
            "user_a_interests": [], "user_b_interests": ["Reading"],
            "user_a_country": "Nepal", "user_b_country": "Nepal",
        })
        self.assertIn("Student A interests: none listed", prompt)
        self.assertIn("Student B interests: Reading", prompt)
        self.assertIn("Shared interests: none", prompt)

    # --- boundary values: missing country data ---
    def test_none_country_renders_as_unknown(self):
        prompt = self.agent.build_prompt({
            "user_a_interests": ["Music"], "user_b_interests": ["Music"],
            "user_a_country": None, "user_b_country": None,
        })
        self.assertIn("Student A country: unknown", prompt)
        self.assertIn("Student B country: unknown", prompt)

    def test_empty_string_country_renders_as_unknown(self):
        prompt = self.agent.build_prompt({
            "user_a_interests": ["Music"], "user_b_interests": ["Music"],
            "user_a_country": "", "user_b_country": "Kenya",
        })
        self.assertIn("Student A country: unknown", prompt)

    # --- unexpected input ---
    def test_raises_when_payload_missing_user_a_interests(self):
        with self.assertRaises(KeyError):
            self.agent.build_prompt({
                "user_b_interests": ["Music"], "user_a_country": "Nepal", "user_b_country": "Nepal",
            })

    def test_raises_when_interests_value_is_not_iterable_of_strings(self):
        # Documents actual behavior rather than leaving it implicit: a
        # None interests list isn't defensively guarded against, so it
        # fails at set()/join() rather than silently producing a blank
        # prompt section.
        with self.assertRaises(TypeError):
            self.agent.build_prompt({
                "user_a_interests": None, "user_b_interests": ["Music"],
                "user_a_country": "Nepal", "user_b_country": "Nepal",
            })


class MatchingAgentParseResponseTests(TestCase):
    """parse_response() input handling: normal and unexpected/malformed input."""

    def setUp(self):
        self.agent = MatchingAgent()

    # --- normal input ---
    def test_parses_valid_json(self):
        result = self.agent.parse_response('{"score": 88, "reasoning": "Strong overlap."}')
        self.assertEqual(result, {"score": 88, "reasoning": "Strong overlap."})

    # --- unexpected input ---
    def test_raises_on_malformed_json(self):
        with self.assertRaises(ValueError):
            self.agent.parse_response("not valid json at all")

    def test_raises_on_empty_string(self):
        with self.assertRaises(ValueError):
            self.agent.parse_response("")
