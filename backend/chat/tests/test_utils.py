from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from chat.models import Message, MessageTranslation
from chat.tests.factories import make_connection, make_direct_conversation, make_university, make_user
from chat.utils import country_code_for, date_label_for, translate_message
from engagement.models import UserEngagement


class TranslateMessageTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        connection = make_connection(self.alice, self.bob)
        self.conversation = make_direct_conversation(connection)
        self.message = Message.objects.create(
            conversation=self.conversation, sender=self.alice, text='Hola'
        )

    def test_normal_input_creates_translation_row(self):
        # normal input, behavior: successful call creates exactly one row
        with patch('chat.utils.translate_text') as mock_translate:
            mock_translate.return_value = {'translated_text': 'Hello', 'stage': 'success'}
            translation = translate_message(self.message, 'English')
        self.assertEqual(translation.translated_text, 'Hello')
        self.assertFalse(translation.used_fallback)
        self.assertEqual(MessageTranslation.objects.count(), 1)

    def test_empty_target_language_returns_none(self):
        # boundary/unexpected input: empty string target language
        translation = translate_message(self.message, '')
        self.assertIsNone(translation)

    def test_none_target_language_returns_none(self):
        # unexpected input: None instead of a string
        translation = translate_message(self.message, None)
        self.assertIsNone(translation)

    def test_repeated_call_is_idempotent(self):
        # behavior: calling twice for the same (message, language) must
        # not create a second row or call the pipeline again
        with patch('chat.utils.translate_text') as mock_translate:
            mock_translate.return_value = {'translated_text': 'Hello', 'stage': 'success'}
            translate_message(self.message, 'English')
            translate_message(self.message, 'English')
        self.assertEqual(MessageTranslation.objects.count(), 1)
        mock_translate.assert_called_once()

    def test_different_languages_create_separate_rows(self):
        # categories of input: two distinct target languages
        with patch('chat.utils.translate_text') as mock_translate:
            mock_translate.return_value = {'translated_text': 'x', 'stage': 'success'}
            translate_message(self.message, 'English')
            translate_message(self.message, 'French')
        self.assertEqual(MessageTranslation.objects.count(), 2)

    def test_pipeline_fallback_marks_used_fallback_true(self):
        # unexpected input (upstream failure): pipeline reports
        # error_fallback — the row still gets created with the original
        # text, and used_fallback must be True so the view can surface
        # the notice
        with patch('chat.utils.translate_text') as mock_translate:
            mock_translate.return_value = {'translated_text': self.message.text, 'stage': 'error_fallback'}
            translation = translate_message(self.message, 'English')
        self.assertTrue(translation.used_fallback)
        self.assertTrue(translation.is_fallback)
        self.assertEqual(translation.translated_text, self.message.text)

    def test_fallback_row_retries_on_next_view_and_succeeds(self):
        # behavior: retry-on-page-load — a cached fallback row must be
        # re-attempted (not trusted forever), and on success the row is
        # updated in place and is_fallback flips to False
        with patch('chat.utils.translate_text') as mock_translate:
            mock_translate.return_value = {'translated_text': self.message.text, 'stage': 'error_fallback'}
            translate_message(self.message, 'English')

            mock_translate.return_value = {'translated_text': 'Hello', 'stage': 'success'}
            translation = translate_message(self.message, 'English')

        self.assertEqual(mock_translate.call_count, 2)
        self.assertFalse(translation.used_fallback)
        self.assertFalse(translation.is_fallback)
        self.assertEqual(translation.translated_text, 'Hello')
        self.assertEqual(MessageTranslation.objects.count(), 1)

    def test_fallback_row_retries_and_fails_again(self):
        # behavior: still down on retry — row stays marked as fallback,
        # no duplicate row created, no crash
        with patch('chat.utils.translate_text') as mock_translate:
            mock_translate.return_value = {'translated_text': self.message.text, 'stage': 'error_fallback'}
            translate_message(self.message, 'English')
            translation = translate_message(self.message, 'English')

        self.assertEqual(mock_translate.call_count, 2)
        self.assertTrue(translation.used_fallback)
        self.assertTrue(translation.is_fallback)
        self.assertEqual(MessageTranslation.objects.count(), 1)

    def test_successful_row_never_retried(self):
        # behavior: a row that already translated successfully must
        # NEVER be re-sent to Gemini on later views
        with patch('chat.utils.translate_text') as mock_translate:
            mock_translate.return_value = {'translated_text': 'Hello', 'stage': 'success'}
            translate_message(self.message, 'English')
            translate_message(self.message, 'English')
            translate_message(self.message, 'English')

        mock_translate.assert_called_once()

    def test_fallback_retry_does_not_double_count_engagement(self):
        # boundary/behavior: engagement should only increment once, on
        # the original creation — retrying a fallback row must not
        # increment translations_used again on eventual success
        with patch('chat.utils.translate_text') as mock_translate:
            mock_translate.return_value = {'translated_text': self.message.text, 'stage': 'error_fallback'}
            translate_message(self.message, 'English', for_user=self.bob)

            mock_translate.return_value = {'translated_text': 'Hello', 'stage': 'success'}
            translate_message(self.message, 'English', for_user=self.bob)

        eng = UserEngagement.objects.get(user=self.bob)
        self.assertEqual(eng.translations_used, 1)

    def test_for_user_increments_engagement_only_on_first_translation(self):
        # behavior: translations_used increments only when a NEW row is
        # created, not on a cache-hit re-fetch
        with patch('chat.utils.translate_text') as mock_translate:
            mock_translate.return_value = {'translated_text': 'Hello', 'stage': 'success'}
            translate_message(self.message, 'English', for_user=self.bob)
            translate_message(self.message, 'English', for_user=self.bob)
        eng = UserEngagement.objects.get(user=self.bob)
        self.assertEqual(eng.translations_used, 1)

    def test_for_user_none_does_not_touch_engagement(self):
        # normal input: no for_user passed, no UserEngagement row expected
        with patch('chat.utils.translate_text') as mock_translate:
            mock_translate.return_value = {'translated_text': 'Hello', 'stage': 'success'}
            translate_message(self.message, 'English')
        self.assertFalse(UserEngagement.objects.filter(user=self.bob).exists())


class DateLabelForTests(TestCase):
    def test_today_returns_today_label(self):
        # boundary/behavior: same calendar day as now
        self.assertEqual(date_label_for(timezone.now()), 'Today')

    def test_yesterday_returns_yesterday_label(self):
        # boundary/behavior: exactly one day back
        yesterday = timezone.now() - timezone.timedelta(days=1)
        self.assertEqual(date_label_for(yesterday), 'Yesterday')

    def test_older_date_returns_formatted_string(self):
        # normal input: anything older than yesterday falls back to a
        # full formatted date
        old = timezone.now() - timezone.timedelta(days=10)
        label = date_label_for(old)
        self.assertNotIn(label, ('Today', 'Yesterday'))
        self.assertIn(str(old.year), label)


class CountryCodeForTests(TestCase):
    def test_known_country_returns_mapped_code(self):
        # normal input
        self.assertEqual(country_code_for('Bangladesh'), 'BD')

    def test_empty_string_returns_placeholder(self):
        # boundary: empty string
        self.assertEqual(country_code_for(''), '—')

    def test_none_returns_placeholder(self):
        # unexpected input: None instead of a string
        self.assertEqual(country_code_for(None), '—')

    def test_unknown_country_falls_back_to_first_two_letters(self):
        # unexpected/invalid input: a country not in the fixed list —
        # shouldn't happen since it's a choice field, but must not crash
        self.assertEqual(country_code_for('Wakanda'), 'WA')
