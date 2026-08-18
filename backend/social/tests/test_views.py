from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from engagement.models import Notification, UserEngagement
from social.models import Comment, Like, Post

User = get_user_model()


class FeedVisibilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="a", email="a@test.edu", password="pw")
        self.client = Client()
        self.client.force_login(self.user)

    def test_old_posts_excluded_from_feed(self):
        # boundary — content just outside the 7-day feed window
        old = Post.objects.create(user=self.user, text="old")
        Post.objects.filter(id=old.id).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        recent = Post.objects.create(user=self.user, text="recent")

        response = self.client.get('/home/')
        content_ids = [
            p.id for _, group in response.context['day_groups'] for p in group
        ]

        self.assertIn(recent.id, content_ids)
        self.assertNotIn(old.id, content_ids)

    def test_empty_feed_returns_no_day_groups(self):
        # boundary — zero posts
        response = self.client.get('/home/')
        self.assertEqual(response.context['day_groups'], [])

    @patch('social.views.is_blocked_either_way')
    def test_blocked_user_posts_excluded(self, mock_blocked):
        # negative case — content from a blocked user must not appear
        blocked_user = User.objects.create_user(username="blocked", email="blocked@test.edu", password="pw")
        Post.objects.create(user=blocked_user, text="from blocked user")
        mock_blocked.side_effect = lambda a, b: b == blocked_user

        response = self.client.get('/home/')
        content_ids = [
            p.id for _, group in response.context['day_groups'] for p in group
        ]

        self.assertEqual(len(content_ids), 0)

    def test_feed_requires_login(self):
        # unexpected input — unauthenticated access
        anon_client = Client()
        response = anon_client.get('/home/')
        self.assertNotEqual(response.status_code, 200)


class ToggleLikeTests(TestCase):
    def setUp(self):
        self.liker = User.objects.create_user(username="liker", email="liker@test.edu", password="pw")
        self.author = User.objects.create_user(username="author", email="author@test.edu", password="pw")
        self.post = Post.objects.create(user=self.author, text="hi")
        self.client = Client()
        self.client.force_login(self.liker)

    def test_first_like_increments_engagement_once(self):
        # normal input
        self.client.post(f'/post/{self.post.id}/like/')

        engagement = UserEngagement.objects.get(user=self.liker)
        self.assertEqual(engagement.likes_given, 1)

    def test_unlike_then_relike_does_not_double_count_engagement(self):
        # behavior — toggle sequence must not inflate the counter
        self.client.post(f'/post/{self.post.id}/like/')  # like
        self.client.post(f'/post/{self.post.id}/like/')  # unlike
        self.client.post(f'/post/{self.post.id}/like/')  # re-like

        engagement = UserEngagement.objects.get(user=self.liker)
        self.assertEqual(engagement.likes_given, 1)
        self.assertEqual(
            Like.objects.filter(post=self.post, user=self.liker).count(), 1
        )

    def test_self_like_does_not_notify(self):
        # negative case — liking your own post must not create a notification
        self.client.logout()
        self.client.force_login(self.author)

        self.client.post(f'/post/{self.post.id}/like/')

        self.assertEqual(Notification.objects.filter(user=self.author).count(), 0)

    def test_like_notifies_post_author(self):
        # normal input / positive case
        self.client.post(f'/post/{self.post.id}/like/')

        self.assertEqual(Notification.objects.filter(user=self.author).count(), 1)

    def test_like_nonexistent_post_returns_404(self):
        # unexpected input — invalid post id
        response = self.client.post('/post/999999/like/')
        self.assertEqual(response.status_code, 404)

    def test_like_requires_post_method(self):
        # behavior — GET must not toggle a like
        self.client.get(f'/post/{self.post.id}/like/')
        self.assertEqual(Like.objects.filter(post=self.post, user=self.liker).count(), 0)


class DeletePermissionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", email="owner@test.edu", password="pw")
        self.other = User.objects.create_user(username="other", email="other@test.edu", password="pw")
        self.post = Post.objects.create(user=self.owner, text="hi")
        self.comment = Comment.objects.create(post=self.post, user=self.owner, text="mine")

    def test_non_owner_cannot_delete_comment(self):
        # negative case — permission boundary
        client = Client()
        client.force_login(self.other)

        client.post(f'/comment/{self.comment.id}/delete/')

        self.assertTrue(Comment.objects.filter(id=self.comment.id).exists())

    def test_owner_can_delete_comment(self):
        # normal input / positive case
        client = Client()
        client.force_login(self.owner)

        client.post(f'/comment/{self.comment.id}/delete/')

        self.assertFalse(Comment.objects.filter(id=self.comment.id).exists())

    def test_non_owner_cannot_delete_post(self):
        # negative case — permission boundary
        client = Client()
        client.force_login(self.other)

        client.post(f'/post/{self.post.id}/delete/')

        self.assertTrue(Post.objects.filter(id=self.post.id).exists())

    def test_owner_can_delete_post(self):
        # normal input / positive case
        client = Client()
        client.force_login(self.owner)

        client.post(f'/post/{self.post.id}/delete/')

        self.assertFalse(Post.objects.filter(id=self.post.id).exists())

    def test_delete_nonexistent_comment_returns_404(self):
        # unexpected input — invalid comment id
        client = Client()
        client.force_login(self.owner)

        response = client.post('/comment/999999/delete/')
        self.assertEqual(response.status_code, 404)


class CreatePostViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="poster", email="poster@test.edu", password="pw")
        self.client = Client()
        self.client.force_login(self.user)

    @patch('social.views.check_message')
    def test_create_post_with_valid_text_saves(self, mock_check):
        # normal input
        mock_check.return_value = {"action": "allow", "stage": "clear"}
        self.client.post('/post/create/', {"text": "a normal post"})
        self.assertEqual(Post.objects.count(), 1)

    @patch('social.views.check_message')
    def test_create_post_with_empty_text_not_saved(self, mock_check):
        # boundary — empty value, invalid form input never reaches the safety check
        mock_check.return_value = {"action": "allow", "stage": "clear"}
        self.client.post('/post/create/', {"text": ""})
        self.assertEqual(Post.objects.count(), 0)
        mock_check.assert_not_called()
