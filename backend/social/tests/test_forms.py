from django.test import TestCase

from social.forms import CommentForm, PostForm


class PostFormTests(TestCase):
    def test_valid_text_passes(self):
        # normal input
        form = PostForm(data={'text': 'A normal moment about campus life.'})
        self.assertTrue(form.is_valid())

    def test_empty_text_rejected(self):
        # boundary — empty value
        form = PostForm(data={'text': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('required', form.errors['text'][0].lower())

    def test_whitespace_only_text_rejected(self):
        # unexpected input — whitespace normalized to empty by CharField(strip=True)
        form = PostForm(data={'text': '   '})
        self.assertFalse(form.is_valid())
        self.assertIn('required', form.errors['text'][0].lower())

    def test_text_over_200_chars_rejected(self):
        # boundary — one character past the max
        form = PostForm(data={'text': 'x' * 201})
        self.assertFalse(form.is_valid())
        self.assertIn('200 characters', form.errors['text'][0])

    def test_text_exactly_200_chars_accepted(self):
        # boundary — exact max length
        form = PostForm(data={'text': 'x' * 200})
        self.assertTrue(form.is_valid())

    def test_text_single_character_accepted(self):
        # boundary — minimum non-empty length
        form = PostForm(data={'text': 'x'})
        self.assertTrue(form.is_valid())

    def test_leading_trailing_whitespace_stripped(self):
        # behavior — normalization of valid input
        form = PostForm(data={'text': '  hello there  '})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['text'], 'hello there')

    def test_missing_text_key_rejected(self):
        # unexpected input — field missing from submitted data entirely
        form = PostForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn('text', form.errors)


class CommentFormTests(TestCase):
    def test_valid_text_passes(self):
        # normal input
        form = CommentForm(data={'text': 'Nice post!'})
        self.assertTrue(form.is_valid())

    def test_empty_text_rejected(self):
        # boundary — empty value
        form = CommentForm(data={'text': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('required', form.errors['text'][0].lower())

    def test_whitespace_only_text_rejected(self):
        # unexpected input — whitespace normalized to empty by CharField(strip=True)
        form = CommentForm(data={'text': '   '})
        self.assertFalse(form.is_valid())
        self.assertIn('required', form.errors['text'][0].lower())

    def test_leading_trailing_whitespace_stripped(self):
        # behavior — normalization of valid input
        form = CommentForm(data={'text': '  nice!  '})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['text'], 'nice!')

    def test_single_character_accepted(self):
        # boundary — minimum non-empty length
        form = CommentForm(data={'text': 'x'})
        self.assertTrue(form.is_valid())

    def test_no_explicit_length_cap_at_form_level(self):
        # unexpected input — form has no server-side max length, unlike PostForm
        long_text = 'x' * 5000
        form = CommentForm(data={'text': long_text})
        self.assertTrue(form.is_valid())

    def test_missing_text_key_rejected(self):
        # unexpected input — field missing from submitted data entirely
        form = CommentForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn('text', form.errors)
