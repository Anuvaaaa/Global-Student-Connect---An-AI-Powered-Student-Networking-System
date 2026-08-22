# TARGET PATH: ai_agents/tests/pure_unit_tests_platform_assistant_agent.py
"""
Pure unit tests for the Platform Assistant agent — no DB, no Gemini, no
mocking. Mocked/agent-level tests live separately in
test_platform_assistant_agent.py.
"""

from django.test import TestCase

from ai_agents.agents.platform_assistant_agent import (
    FALLBACK_MESSAGES,
    AssistantResponse,
    PlatformAssistantAgent,
    format_history,
    get_fallback_message,
)


class FormatHistoryTests(TestCase):

    def test_empty_history_returns_placeholder(self):
        # boundary condition: zero messages
        result = format_history([])
        self.assertEqual(result, "(no earlier messages in this conversation)")

    def test_single_message_formats_correctly(self):
        # normal input
        history = [{"role": "user", "content": "How do groups form?"}]
        result = format_history(history)
        self.assertEqual(result, "Student: How do groups form?")

    def test_alternating_roles_labelled_correctly(self):
        # behavior: user/assistant turns get distinct speaker labels
        history = [
            {"role": "user", "content": "What is a badge?"},
            {"role": "assistant", "content": "A badge is earned by..."},
        ]
        result = format_history(history)
        self.assertIn("Student: What is a badge?", result)
        self.assertIn("Assistant: A badge is earned by...", result)

    def test_history_longer_than_cap_is_trimmed_to_recent_turns(self):
        # boundary condition: more turns than MAX_HISTORY_TURNS (max case)
        history = [{"role": "user", "content": f"question {i}"} for i in range(20)]
        result = format_history(history)
        self.assertNotIn("question 0", result)
        self.assertIn("question 19", result)

    def test_missing_content_key_defaults_to_empty_string(self):
        # unexpected input: malformed turn dict missing "content"
        history = [{"role": "user"}]
        result = format_history(history)
        self.assertEqual(result, "Student: ")

    def test_unknown_role_falls_back_to_assistant_label(self):
        # negative/unexpected input: role is neither "user" nor "assistant"
        history = [{"role": "system", "content": "internal note"}]
        result = format_history(history)
        self.assertIn("Assistant: internal note", result)


class FallbackMessageTests(TestCase):

    def test_returns_one_of_the_known_fallback_messages(self):
        # normal input / behavior: output is always a valid apology line
        result = get_fallback_message()
        self.assertIn(result, FALLBACK_MESSAGES)

    def test_never_returns_empty_string(self):
        # boundary condition: minimum acceptable output length
        result = get_fallback_message()
        self.assertGreater(len(result), 0)


class BuildPromptTests(TestCase):

    def setUp(self):
        self.agent = PlatformAssistantAgent()

    def test_prompt_includes_question_and_history(self):
        # normal input
        payload = {
            "question": "How do I report someone?",
            "history": [{"role": "user", "content": "hi"}],
        }
        prompt = self.agent.build_prompt(payload)
        self.assertIn("How do I report someone?", prompt)
        self.assertIn("Student: hi", prompt)

    def test_prompt_handles_missing_history_key(self):
        # boundary condition: history key absent entirely, not just empty
        payload = {"question": "What is GSC?"}
        prompt = self.agent.build_prompt(payload)
        self.assertIn("(no earlier messages in this conversation)", prompt)

    def test_missing_question_key_raises_key_error(self):
        # unexpected input: required field missing entirely
        payload = {"history": []}
        with self.assertRaises(KeyError):
            self.agent.build_prompt(payload)


class ParseResponseTests(TestCase):

    def setUp(self):
        self.agent = PlatformAssistantAgent()

    def test_parses_clean_json(self):
        # normal input
        raw = '{"answer": "Check your Matching page.", "in_scope": true}'
        result = self.agent.parse_response(raw)
        self.assertEqual(result["answer"], "Check your Matching page.")
        self.assertTrue(result["in_scope"])

    def test_parses_json_wrapped_in_markdown_fences(self):
        # negative input: Gemini sometimes wraps JSON in fences anyway
        raw = '```json\n{"answer": "Go to Missions.", "in_scope": true}\n```'
        result = self.agent.parse_response(raw)
        self.assertEqual(result["answer"], "Go to Missions.")

    def test_malformed_json_raises(self):
        # unexpected input: not valid JSON at all
        with self.assertRaises(Exception):
            self.agent.parse_response("not json at all")


class AgentConfigTests(TestCase):

    def test_uses_secondary_api_key_group(self):
        # behavior: routes on the shared secondary pool with Verification/Translation
        self.assertEqual(PlatformAssistantAgent.api_key_group, "secondary")

    def test_enforces_response_schema(self):
        # behavior: structured output is enforced, not just requested
        self.assertIs(PlatformAssistantAgent.response_schema, AssistantResponse)
