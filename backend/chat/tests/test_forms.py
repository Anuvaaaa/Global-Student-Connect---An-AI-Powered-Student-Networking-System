from django.test import TestCase

from chat.forms import MessageForm


class MessageFormTests(TestCase):
    def test_normal_input_is_valid(self):
        # normal input
        form = MessageForm(data={'text': 'Hey, how are you?'})
        self.assertTrue(form.is_valid())

    def test_empty_string_is_invalid(self):
        # boundary: minimum (0 chars)
        form = MessageForm(data={'text': ''})
        self.assertFalse(form.is_valid())

    def test_whitespace_only_is_invalid(self):
        # unexpected/invalid input: Django's CharField strips whitespace
        # by default before the required check runs, so '   ' becomes ''
        # at the framework level — Django's built-in required message
        # fires here, not clean_text()'s custom message (that message is
        # only reachable if the field's `required` were ever set False)
        form = MessageForm(data={'text': '   '})
        self.assertFalse(form.is_valid())
        self.assertIn('required', form.errors['text'][0].lower())

    def test_exactly_500_chars_is_valid(self):
        # boundary: maximum allowed length
        form = MessageForm(data={'text': 'a' * 500})
        self.assertTrue(form.is_valid())

    def test_501_chars_is_invalid(self):
        # boundary: one over the maximum
        form = MessageForm(data={'text': 'a' * 501})
        self.assertFalse(form.is_valid())
        self.assertIn('too long', form.errors['text'][0])

    def test_leading_trailing_whitespace_is_stripped(self):
        # behavior: clean_text() strips before saving
        form = MessageForm(data={'text': '  hello  '})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['text'], 'hello')

    def test_missing_field_is_invalid(self):
        # unexpected/invalid input: no 'text' key at all
        form = MessageForm(data={})
        self.assertFalse(form.is_valid())

    def test_unicode_and_emoji_input_is_valid(self):
        # categories of input: non-ASCII content should be accepted the
        # same as plain ASCII, since GSC is an international-student app
        form = MessageForm(data={'text': 'こんにちは 👋 مرحبا'})
        self.assertTrue(form.is_valid())
