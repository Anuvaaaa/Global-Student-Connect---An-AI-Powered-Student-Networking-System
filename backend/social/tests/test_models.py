from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from social.models import Comment, Interest, Like, Post

User = get_user_model()


class LikeModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="a", email="a@test.edu", password="pw")
        self.post = Post.objects.create(user=self.user, text="hi")

    def test_unique_like_constraint(self):
        # negative input / duplicate data — same (post, user) pair twice
        Like.objects.create(post=self.post, user=self.user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Like.objects.create(post=self.post, user=self.user)

    def test_like_defaults_active(self):
        # normal input — default field value on creation
        like = Like.objects.create(post=self.post, user=self.user)
        self.assertTrue(like.active)

    def test_like_can_be_deactivated_and_reactivated(self):
        # behavior — active flag toggles both directions
        like = Like.objects.create(post=self.post, user=self.user)
        like.active = False
        like.save(update_fields=['active'])
        like.refresh_from_db()
        self.assertFalse(like.active)

        like.active = True
        like.save(update_fields=['active'])
        like.refresh_from_db()
        self.assertTrue(like.active)


class PostCascadeTests(TestCase):
    def test_deleting_post_deletes_comments_and_likes(self):
        # behavior — cascade delete across related models
        user = User.objects.create_user(username="b", email="b@test.edu", password="pw")
        post = Post.objects.create(user=user, text="hi")
        Comment.objects.create(post=post, user=user, text="nice")
        Like.objects.create(post=post, user=user)

        post.delete()

        self.assertEqual(Comment.objects.count(), 0)
        self.assertEqual(Like.objects.count(), 0)

    def test_deleting_user_deletes_their_posts(self):
        # behavior — cascade delete from User side
        user = User.objects.create_user(username="c", email="c@test.edu", password="pw")
        Post.objects.create(user=user, text="hi")

        user.delete()

        self.assertEqual(Post.objects.count(), 0)


class CommentModelTests(TestCase):
    def test_comment_str_and_fields(self):
        # normal input
        user = User.objects.create_user(username="d", email="d@test.edu", password="pw")
        post = Post.objects.create(user=user, text="hi")
        comment = Comment.objects.create(post=post, user=user, text="nice post")

        self.assertEqual(comment.post, post)
        self.assertEqual(comment.user, user)
        self.assertIsNotNone(comment.created_at)

    def test_multiple_comments_on_same_post_allowed(self):
        # normal input — no uniqueness constraint on (post, user) for comments
        user = User.objects.create_user(username="e", email="e@test.edu", password="pw")
        post = Post.objects.create(user=user, text="hi")
        Comment.objects.create(post=post, user=user, text="first")
        Comment.objects.create(post=post, user=user, text="second")

        self.assertEqual(post.comments.count(), 2)


class InterestModelTests(TestCase):
    def test_unique_interest_name_constraint(self):
        # negative input / duplicate data
        Interest.objects.create(name="Coding")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Interest.objects.create(name="Coding")

    def test_interest_str_returns_name(self):
        # normal input
        interest = Interest.objects.create(name="Music")
        self.assertEqual(str(interest), "Music")
