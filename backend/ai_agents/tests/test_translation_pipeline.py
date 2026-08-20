from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from ai_agents.services.translation_pipeline import (
    BREAKER_OPEN_KEY, FAILURE_COUNT_KEY, FAILURE_THRESHOLD, translate_text,
)


class TranslateTextTests(TestCase):
    def setUp(self):
        # boundary/behavior: every test starts with a closed breaker and
        # a zeroed failure count, regardless of what a previous test left behind
        cache.delete(BREAKER_OPEN_KEY)
        cache.delete(FAILURE_COUNT_KEY)

    def tearDown(self):
        cache.delete(BREAKER_OPEN_KEY)
        cache.delete(FAILURE_COUNT_KEY)

    def test_normal_input_returns_success_stage(self):
        # normal input
        fake_agent = MagicMock()
        fake_agent.run.return_value = {'translated_text': 'Hola', 'detected_source_language': 'English'}
        with patch('ai_agents.factory.AgentFactory.get_agent', return_value=fake_agent):
            result = translate_text('Hello', 'Spanish')
        self.assertEqual(result, {'translated_text': 'Hola', 'stage': 'success'})

    def test_empty_text_returns_skipped(self):
        # boundary: empty string input, never calls the agent at all
        with patch('ai_agents.factory.AgentFactory.get_agent') as mock_get:
            result = translate_text('', 'Spanish')
        self.assertEqual(result['stage'], 'skipped')
        mock_get.assert_not_called()

    def test_empty_target_language_returns_skipped(self):
        # boundary: empty target language
        with patch('ai_agents.factory.AgentFactory.get_agent') as mock_get:
            result = translate_text('Hello', '')
        self.assertEqual(result['stage'], 'skipped')
        mock_get.assert_not_called()

    def test_agent_exception_falls_back_to_original_text(self):
        # unexpected input: Gemini call raises — must never propagate,
        # must return the original text unchanged
        fake_agent = MagicMock()
        fake_agent.run.side_effect = Exception('quota exceeded')
        with patch('ai_agents.factory.AgentFactory.get_agent', return_value=fake_agent):
            result = translate_text('Hello', 'Spanish')
        self.assertEqual(result, {'translated_text': 'Hello', 'stage': 'error_fallback'})

    def test_empty_translated_text_in_response_treated_as_failure(self):
        # unexpected/invalid input: malformed agent response with a blank
        # translation must fall back rather than store an empty string
        fake_agent = MagicMock()
        fake_agent.run.return_value = {'translated_text': '', 'detected_source_language': 'English'}
        with patch('ai_agents.factory.AgentFactory.get_agent', return_value=fake_agent):
            result = translate_text('Hello', 'Spanish')
        self.assertEqual(result['stage'], 'error_fallback')
        self.assertEqual(result['translated_text'], 'Hello')

    def test_success_resets_failure_counter(self):
        # behavior: a successful call after prior failures clears the
        # consecutive-failure count rather than letting it accumulate
        cache.set(FAILURE_COUNT_KEY, FAILURE_THRESHOLD - 1)
        fake_agent = MagicMock()
        fake_agent.run.return_value = {'translated_text': 'Hola', 'detected_source_language': 'English'}
        with patch('ai_agents.factory.AgentFactory.get_agent', return_value=fake_agent):
            translate_text('Hello', 'Spanish')
        self.assertIsNone(cache.get(FAILURE_COUNT_KEY))

    def test_breaker_opens_after_threshold_consecutive_failures(self):
        # boundary: exactly FAILURE_THRESHOLD consecutive failures trips the breaker
        fake_agent = MagicMock()
        fake_agent.run.side_effect = Exception('down')
        with patch('ai_agents.factory.AgentFactory.get_agent', return_value=fake_agent):
            for _ in range(FAILURE_THRESHOLD):
                translate_text('Hello', 'Spanish')
        self.assertTrue(cache.get(BREAKER_OPEN_KEY))

    def test_breaker_open_skips_agent_call_entirely(self):
        # behavior: once open, subsequent calls short-circuit to fallback
        # without touching AgentFactory at all
        cache.set(BREAKER_OPEN_KEY, True, timeout=60)
        with patch('ai_agents.factory.AgentFactory.get_agent') as mock_get:
            result = translate_text('Hello', 'Spanish')
        self.assertEqual(result['stage'], 'error_fallback')
        mock_get.assert_not_called()

    def test_one_failure_below_threshold_does_not_open_breaker(self):
        # boundary: FAILURE_THRESHOLD - 1 failures must leave the breaker closed
        fake_agent = MagicMock()
        fake_agent.run.side_effect = Exception('down')
        with patch('ai_agents.factory.AgentFactory.get_agent', return_value=fake_agent):
            for _ in range(FAILURE_THRESHOLD - 1):
                translate_text('Hello', 'Spanish')
        self.assertFalse(cache.get(BREAKER_OPEN_KEY, False))
