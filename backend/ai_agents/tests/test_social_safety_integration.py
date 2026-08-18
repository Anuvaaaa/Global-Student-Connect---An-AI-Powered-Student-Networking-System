from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from ai_agents.models import SafetyFlag
from engagement.models import Notification, UserEngagement
from social.models import Comment, Post

User = get_user_model()


class PostSafetyIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="a", email="a@test.edu", password="pw")
        self.client = Client()
        self.client.force_login(self.user)

    @patch("social.views.check_message")
    def test_clean_post_saves_no_flag(self, mock_check):
        # normal input
        mock_check.return_value = {"action": "allow", "stage": "clear"}

        self.client.post("/post/create/", {"text": "hello world"})

        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(SafetyFlag.objects.count(), 0)

    @patch("social.views.check_message")
    def test_high_severity_post_blocked_not_saved(self, mock_check):
        # negative case — high severity triggers auto-block
        mock_check.return_value = {
            "action": "auto_block", "stage": "llm", "flagged": True,
            "category": "harassment", "severity": "high",
            "confidence": 0.95, "reasoning": "explicit threat",
        }

        self.client.post("/post/create/", {"text": "bad text"})

        self.assertEqual(Post.objects.count(), 0)
        flag = SafetyFlag.objects.get()
        self.assertIsNone(flag.post)
        self.assertEqual(flag.blocked_text, "bad text")
        self.assertEqual(flag.user, self.user)
        self.assertEqual(flag.severity, "high")

    @patch("social.views.check_message")
    def test_medium_severity_post_saved_and_queued(self, mock_check):
        # behavior — medium severity still publishes, but queues for review
        mock_check.return_value = {
            "action": "queue_human_review", "stage": "llm", "flagged": True,
            "category": "spam", "severity": "medium",
            "confidence": 0.7, "reasoning": "borderline spam",
        }

        self.client.post("/post/create/", {"text": "sketchy text"})

        post = Post.objects.get()
        flag = SafetyFlag.objects.get()
        self.assertEqual(flag.post, post)
        self.assertEqual(flag.status, "open")
        self.assertIsNone(flag.blocked_text)

    @patch("social.views.check_message")
    def test_low_severity_post_saved_and_queued(self, mock_check):
        # boundary — lowest flagged severity still queues, not blocked
        mock_check.return_value = {
            "action": "queue_human_review", "stage": "llm", "flagged": True,
            "category": "other", "severity": "low",
            "confidence": 0.5, "reasoning": "mild concern",
        }

        self.client.post("/post/create/", {"text": "mildly odd text"})

        self.assertEqual(Post.objects.count(), 1)
        flag = SafetyFlag.objects.get()
        self.assertEqual(flag.severity, "low")

    @patch("social.views.check_message")
    def test_gemini_down_fails_open_post_still_saves(self, mock_check):
        # unexpected input — upstream AI service failure
        mock_check.return_value = {"action": "allow", "stage": "error_fallback"}

        self.client.post("/post/create/", {"text": "normal text"})

        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(SafetyFlag.objects.count(), 0)


class CommentSafetyIntegrationTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="author", email="author@test.edu", password="pw")
        self.commenter = User.objects.create_user(username="commenter", email="c@test.edu", password="pw")
        self.post = Post.objects.create(user=self.author, text="a post")
        self.client = Client()
        self.client.force_login(self.commenter)

    @patch("social.views.check_message")
    def test_blocked_comment_not_saved_no_engagement_credit(self, mock_check):
        # negative case — blocked content must not earn engagement credit
        mock_check.return_value = {
            "action": "auto_block", "stage": "llm", "flagged": True,
            "category": "harassment", "severity": "high",
            "confidence": 0.9, "reasoning": "abusive",
        }

        self.client.post(f"/post/{self.post.id}/comment/", {"text": "abusive text"})

        self.assertEqual(Comment.objects.count(), 0)
        flag = SafetyFlag.objects.get()
        self.assertIsNone(flag.comment)
        self.assertEqual(flag.blocked_text, "abusive text")

        engagement = UserEngagement.objects.filter(user=self.commenter).first()
        self.assertTrue(engagement is None or engagement.comments_made == 0)

    @patch("social.views.check_message")
    def test_flagged_comment_still_saves_and_links(self, mock_check):
        # behavior — queued comment is saved and linked to its SafetyFlag
        mock_check.return_value = {
            "action": "queue_human_review", "stage": "llm", "flagged": True,
            "category": "other", "severity": "low",
            "confidence": 0.6, "reasoning": "mildly rude",
        }

        self.client.post(f"/post/{self.post.id}/comment/", {"text": "rude text"})

        comment = Comment.objects.get()
        flag = SafetyFlag.objects.get()
        self.assertEqual(flag.comment, comment)
        self.assertEqual(flag.status, "open")

    @patch("social.views.check_message")
    def test_blocked_comment_does_not_notify_post_author(self, mock_check):
        # negative case — blocked content must not trigger a notification
        mock_check.return_value = {
            "action": "auto_block", "stage": "llm", "flagged": True,
            "category": "harassment", "severity": "high",
            "confidence": 0.9, "reasoning": "abusive",
        }

        self.client.post(f"/post/{self.post.id}/comment/", {"text": "abusive text"})

        self.assertEqual(Notification.objects.filter(user=self.author).count(), 0)

    @patch("social.views.check_message")
    def test_clean_comment_on_own_post_no_self_notification(self, mock_check):
        # behavior — commenting on your own post must not self-notify
        mock_check.return_value = {"action": "allow", "stage": "clear"}
        self.client.logout()
        self.client.force_login(self.author)

        self.client.post(f"/post/{self.post.id}/comment/", {"text": "note to self"})

        self.assertEqual(Notification.objects.filter(user=self.author).count(), 0)

    @patch("social.views.check_message")
    def test_comment_on_nonexistent_post_returns_404(self, mock_check):
        # unexpected input — invalid post id
        mock_check.return_value = {"action": "allow", "stage": "clear"}
        response = self.client.post("/post/999999/comment/", {"text": "hello"})
        self.assertEqual(response.status_code, 404)
        mock_check.assert_not_called()
