from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from social.models import Comment, Like, Post

User = get_user_model()


class LikeModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="a", email="a@test.edu", password="pw")
        self.post = Post.objects.create(user=self.user, text="hi")

    def test_unique_like_constraint(self):
        Like.objects.create(post=self.post, user=self.user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Like.objects.create(post=self.post, user=self.user)

    def test_like_defaults_active(self):
        like = Like.objects.create(post=self.post, user=self.user)
        self.assertTrue(like.active)


class PostCascadeTests(TestCase):
    def test_deleting_post_deletes_comments_and_likes(self):
        user = User.objects.create_user(username="b", email="b@test.edu", password="pw")
        post = Post.objects.create(user=user, text="hi")
        Comment.objects.create(post=post, user=user, text="nice")
        Like.objects.create(post=post, user=user)

        post.delete()

        self.assertEqual(Comment.objects.count(), 0)
        self.assertEqual(Like.objects.count(), 0)


class CommentModelTests(TestCase):
    def test_comment_str_and_fields(self):
        user = User.objects.create_user(username="c", email="c@test.edu", password="pw")
        post = Post.objects.create(user=user, text="hi")
        comment = Comment.objects.create(post=post, user=user, text="nice post")

        self.assertEqual(comment.post, post)
        self.assertEqual(comment.user, user)
        self.assertIsNotNone(comment.created_at)
