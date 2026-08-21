from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from accounts.utils import get_block_message


def _user(is_banned=False, suspended_until=None):
    # Lightweight stand-in for a User row — get_block_message only reads
    # two attributes, so a real model instance (and the DB query that
    # would come with one) isn't needed.
    return SimpleNamespace(is_banned=is_banned, suspended_until=suspended_until)


class GetBlockMessageTests(SimpleTestCase):

    def setUp(self):
        self.now = timezone.now()

    def test_normal_input_clear_user_returns_none(self):
        # Normal input: not banned, no suspension — allowed to sign in.
        result = get_block_message(_user(), self.now)
        self.assertIsNone(result)

    def test_input_category_banned_user_returns_ban_message(self):
        # Positive category: banned account.
        result = get_block_message(_user(is_banned=True), self.now)
        self.assertIn("permanently banned", result)

    def test_input_category_suspended_user_returns_suspension_message(self):
        # Positive category: suspended but not banned.
        future = self.now + timedelta(days=3)
        result = get_block_message(_user(suspended_until=future), self.now)
        self.assertIn("suspended until", result)

    def test_behavior_ban_takes_priority_over_suspension(self):
        # Behavior: a user can technically have both fields set (e.g. a
        # stale suspended_until left over from before a ban was applied).
        # Ban must win — the message should not blend or default to
        # the suspension text.
        future = self.now + timedelta(days=3)
        result = get_block_message(_user(is_banned=True, suspended_until=future), self.now)
        self.assertIn("permanently banned", result)
        self.assertNotIn("suspended until", result)

    def test_boundary_suspension_expiring_exactly_now_is_not_blocked(self):
        # Boundary: suspended_until == now is NOT "> now", so this is the
        # instant the suspension lifts — must not block.
        result = get_block_message(_user(suspended_until=self.now), self.now)
        self.assertIsNone(result)

    def test_boundary_suspension_one_second_in_future_is_blocked(self):
        # Boundary: the smallest possible margin that still counts as
        # "still suspended".
        result = get_block_message(
            _user(suspended_until=self.now + timedelta(seconds=1)), self.now
        )
        self.assertIsNotNone(result)

    def test_unexpected_input_expired_suspension_returns_none(self):
        # Unexpected input: suspended_until is set but already in the
        # past — a stale/unlifted field shouldn't keep blocking sign-in
        # forever.
        past = self.now - timedelta(days=1)
        result = get_block_message(_user(suspended_until=past), self.now)
        self.assertIsNone(result)

    def test_unexpected_input_suspended_until_none_returns_none(self):
        # Unexpected input: explicit None rather than an unset attribute —
        # confirms the falsy check, not just "attribute missing", is
        # what's relied on.
        result = get_block_message(_user(suspended_until=None), self.now)
        self.assertIsNone(result)
