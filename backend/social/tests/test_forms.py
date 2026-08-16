from django.test import TestCase

from social.forms import CommentForm, PostForm


class PostFormTests(TestCase):
    def test_valid_text_passes(self):
        form = PostForm(data={'text': 'A normal moment about campus life.'})
        self.assertTrue(form.is_valid())

    def test_empty_text_rejected(self):
        form = PostForm(data={'text': ''})
        self.assertFalse(form.is_valid())
        # Caught by Django's built-in required-field check, not our
        # custom clean_text() — CharField's default strip=True (since
        # Django 4.2) normalizes the input before our validation runs.
        self.assertIn('required', form.errors['text'][0].lower())

    def test_whitespace_only_text_rejected(self):
        # strip=True (CharField default since Django 4.2) normalizes
        # whitespace-only input to '' at the widget level, BEFORE our
        # clean_text() runs — so this hits the same built-in required
        # check as a truly empty submission, not our custom message.
        form = PostForm(data={'text': '   '})
        self.assertFalse(form.is_valid())
        self.assertIn('required', form.errors['text'][0].lower())

    def test_text_over_200_chars_rejected(self):
        form = PostForm(data={'text': 'x' * 201})
        self.assertFalse(form.is_valid())
        self.assertIn('200 characters', form.errors['text'][0])

    def test_text_exactly_200_chars_accepted(self):
        # Boundary check — 200 is the limit, not the cutoff.
        form = PostForm(data={'text': 'x' * 200})
        self.assertTrue(form.is_valid())

    def test_leading_trailing_whitespace_stripped(self):
        form = PostForm(data={'text': '  hello there  '})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['text'], 'hello there')


class CommentFormTests(TestCase):
    def test_valid_text_passes(self):
        form = CommentForm(data={'text': 'Nice post!'})
        self.assertTrue(form.is_valid())

    def test_empty_text_rejected(self):
        form = CommentForm(data={'text': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('required', form.errors['text'][0].lower())

    def test_whitespace_only_text_rejected(self):
        # Same strip=True behavior as PostForm — see note there.
        form = CommentForm(data={'text': '   '})
        self.assertFalse(form.is_valid())
        self.assertIn('required', form.errors['text'][0].lower())

    def test_leading_trailing_whitespace_stripped(self):
        form = CommentForm(data={'text': '  nice!  '})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['text'], 'nice!')

    def test_no_explicit_length_cap_at_form_level(self):
        # Unlike PostForm, CommentForm's clean_text() has no length
        # check — the 500-char cap only exists client-side (maxlength
        # on the <input> in home.html) and via Comment.text being a
        # TextField (effectively unbounded at the DB level too). This
        # test documents that the form itself won't reject long text,
        # so it doesn't silently start failing if someone assumes
        # there's server-side enforcement that isn't actually there.
        long_text = 'x' * 5000
        form = CommentForm(data={'text': long_text})
        self.assertTrue(form.is_valid())
