import json

from django.test import SimpleTestCase

from ai_agents.agents.translation_agent import TranslationAgent, TranslationResult


class TranslationAgentConfigTests(SimpleTestCase):
    def setUp(self):
        self.agent = TranslationAgent()

    def test_uses_secondary_api_key_group(self):
        # behavior: must route onto the secondary key, separate from
        # Safety/Matching/Nudge's primary key
        self.assertEqual(self.agent.api_key_group, 'secondary')

    def test_temperature_pinned_to_zero(self):
        # behavior: deterministic output for repeated identical calls
        self.assertEqual(self.agent.temperature, 0)

    def test_response_schema_is_translation_result(self):
        # behavior
        self.assertIs(self.agent.response_schema, TranslationResult)


class TranslationAgentBuildPromptTests(SimpleTestCase):
    def setUp(self):
        self.agent = TranslationAgent()

    def test_normal_input_includes_text_and_language(self):
        # normal input
        prompt = self.agent.build_prompt({'text': 'Hello there', 'target_language': 'Spanish'})
        self.assertIn('Hello there', prompt)
        self.assertIn('Spanish', prompt)

    def test_empty_text_does_not_raise(self):
        # boundary: empty string message
        prompt = self.agent.build_prompt({'text': '', 'target_language': 'French'})
        self.assertIn('French', prompt)

    def test_missing_target_language_key_raises_key_error(self):
        # unexpected/invalid input: caller contract requires both keys —
        # a missing key should fail loudly, not silently produce a bad prompt
        with self.assertRaises(KeyError):
            self.agent.build_prompt({'text': 'Hello'})

    def test_unicode_text_included_verbatim(self):
        # categories of input: non-Latin script source text
        prompt = self.agent.build_prompt({'text': 'こんにちは', 'target_language': 'English'})
        self.assertIn('こんにちは', prompt)


class TranslationAgentParseResponseTests(SimpleTestCase):
    def setUp(self):
        self.agent = TranslationAgent()

    def test_normal_input_plain_json(self):
        # normal input
        raw = json.dumps({'translated_text': 'Bonjour', 'detected_source_language': 'English'})
        result = self.agent.parse_response(raw)
        self.assertEqual(result['translated_text'], 'Bonjour')

    def test_json_wrapped_in_code_fence_is_stripped(self):
        # behavior: shared parse_json() helper strips ```json fences
        raw = '```json\n{"translated_text": "Hola", "detected_source_language": "English"}\n```'
        result = self.agent.parse_response(raw)
        self.assertEqual(result['translated_text'], 'Hola')

    def test_malformed_json_raises(self):
        # unexpected/invalid input: not valid JSON at all
        with self.assertRaises(json.JSONDecodeError):
            self.agent.parse_response('not json at all')

    def test_empty_string_raises(self):
        # boundary: empty response body
        with self.assertRaises(json.JSONDecodeError):
            self.agent.parse_response('')
