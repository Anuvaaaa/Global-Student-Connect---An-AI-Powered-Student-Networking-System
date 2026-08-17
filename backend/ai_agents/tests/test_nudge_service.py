# TARGET PATH: ai_agents/tests/test_nudge_service.py
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from ai_agents.models import NudgeLog
from ai_agents.services.nudge_service import generate_nudge, MIN_PROGRESS_DELTA_PCT
from engagement.models import Badge, Mission, Notification

User = get_user_model()


def _make_user(email="student@example.edu"):
    from accounts.models import University

    university, _ = University.objects.get_or_create(
        domain="example.edu", defaults={"name": "Example University"},
    )
    return User.objects.create_user(
        username=email, email=email, google_id=f"gid-{email}",
        university=university, is_verified=True, password="testpass123",
    )


def _make_badge(**overrides):
    defaults = dict(
        key="social_butterfly_gold", name="Social Butterfly", threshold=50,
        metric="messages_sent", tier="gold", badge_group="social_butterfly",
    )
    defaults.update(overrides)
    return Badge.objects.create(**defaults)


def _make_mission(**overrides):
    defaults = dict(
        key="daily_chat", name="Send 3 messages", frequency="daily", target=3,
    )
    defaults.update(overrides)
    return Mission.objects.create(**defaults)


class NudgeServiceBadgeTests(TestCase):
    """Normal-input behavior for badge nudges: creation, notification, rate-limiting."""

    def setUp(self):
        self.user = _make_user()
        self.badge = _make_badge()

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_creates_nudgelog_and_notification_on_first_nudge(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"nudge_text": "Almost there on Social Butterfly!"}
        mock_get_agent.return_value = mock_agent

        result = generate_nudge(self.user, progress_pct=75, badge=self.badge)

        self.assertIsNotNone(result)
        self.assertEqual(result.nudge_type, "badge_progress")
        self.assertEqual(result.badge, self.badge)
        self.assertIsNone(result.mission)
        self.assertEqual(result.progress_pct, 75)
        self.assertEqual(result.message_text, "Almost there on Social Butterfly!")
        self.assertTrue(
            Notification.objects.filter(user=self.user, type="badge").exists()
        )

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_skips_when_progress_delta_below_threshold(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"nudge_text": "first nudge"}
        mock_get_agent.return_value = mock_agent

        generate_nudge(self.user, progress_pct=75, badge=self.badge)
        # Progress moved only 5 points — below MIN_PROGRESS_DELTA_PCT (15)
        result = generate_nudge(self.user, progress_pct=80, badge=self.badge)

        self.assertIsNone(result)
        self.assertEqual(NudgeLog.objects.filter(user=self.user, badge=self.badge).count(), 1)

    def test_raises_when_neither_badge_nor_mission_given(self):
        with self.assertRaises(ValueError):
            generate_nudge(self.user, progress_pct=80)

    def test_raises_when_both_badge_and_mission_given(self):
        mission = _make_mission()
        with self.assertRaises(ValueError):
            generate_nudge(self.user, progress_pct=80, badge=self.badge, mission=mission)


class NudgeServiceMissionTests(TestCase):
    def setUp(self):
        self.user = _make_user(email="mission-student@example.edu")
        self.mission = _make_mission()

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_creates_nudgelog_for_mission(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"nudge_text": "One more message finishes today's mission!"}
        mock_get_agent.return_value = mock_agent

        result = generate_nudge(self.user, progress_pct=66, mission=self.mission)

        self.assertIsNotNone(result)
        self.assertEqual(result.nudge_type, "mission_progress")
        self.assertEqual(result.mission, self.mission)
        self.assertIsNone(result.badge)

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_badge_and_mission_rate_limits_tracked_independently(self, mock_get_agent):
        badge = _make_badge(key="different_badge")
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"nudge_text": "nudge"}
        mock_get_agent.return_value = mock_agent

        generate_nudge(self.user, progress_pct=75, badge=badge)
        # Different target (mission, not badge) — should NOT be rate-limited
        # by the badge nudge just sent, even though it's the same user.
        result = generate_nudge(self.user, progress_pct=75, mission=self.mission)

        self.assertIsNotNone(result)


class NudgeServiceRateLimitBoundaryTests(TestCase):
    """Boundary conditions on the MIN_PROGRESS_DELTA_PCT rate-limit check."""

    def setUp(self):
        self.user = _make_user(email="boundary-student@example.edu")
        self.badge = _make_badge()

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_delta_one_below_threshold_is_skipped(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"nudge_text": "nudge"}
        mock_get_agent.return_value = mock_agent

        generate_nudge(self.user, progress_pct=70, badge=self.badge)
        result = generate_nudge(self.user, progress_pct=70 + MIN_PROGRESS_DELTA_PCT - 1, badge=self.badge)

        self.assertIsNone(result)

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_delta_exactly_at_threshold_sends(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"nudge_text": "nudge"}
        mock_get_agent.return_value = mock_agent

        generate_nudge(self.user, progress_pct=70, badge=self.badge)
        result = generate_nudge(self.user, progress_pct=70 + MIN_PROGRESS_DELTA_PCT, badge=self.badge)

        self.assertIsNotNone(result)

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_progress_pct_at_zero(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"nudge_text": "nudge"}
        mock_get_agent.return_value = mock_agent

        result = generate_nudge(self.user, progress_pct=0, badge=self.badge)

        self.assertIsNotNone(result)
        self.assertEqual(result.progress_pct, 0)

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_progress_pct_at_max(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"nudge_text": "nudge"}
        mock_get_agent.return_value = mock_agent

        result = generate_nudge(self.user, progress_pct=100, badge=self.badge)

        self.assertIsNotNone(result)
        self.assertEqual(result.progress_pct, 100)

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_regressing_progress_is_treated_as_below_threshold_not_error(self, mock_get_agent):
        # A user's tracked progress dropping (e.g. a new mission period
        # starting over) produces a negative delta. This should behave
        # exactly like any other below-threshold delta — silently
        # skipped — not raise or behave unexpectedly.
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"nudge_text": "nudge"}
        mock_get_agent.return_value = mock_agent

        generate_nudge(self.user, progress_pct=80, badge=self.badge)
        result = generate_nudge(self.user, progress_pct=20, badge=self.badge)

        self.assertIsNone(result)


class NudgeServiceUnexpectedInputTests(TestCase):
    """Failure modes: Gemini unreachable, and malformed Gemini responses."""

    def setUp(self):
        self.user = _make_user(email="failure-student@example.edu")
        self.badge = _make_badge()

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_fails_open_when_agent_unavailable(self, mock_get_agent):
        mock_get_agent.side_effect = Exception("quota exhausted")

        result = generate_nudge(self.user, progress_pct=90, badge=self.badge)

        self.assertIsNone(result)
        self.assertEqual(NudgeLog.objects.filter(user=self.user).count(), 0)

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_fails_open_when_response_missing_nudge_text(self, mock_get_agent):
        # A malformed/unexpected Gemini response (missing the expected
        # key) must fail open the same as an unreachable agent — not
        # raise an uncaught KeyError into the calling signal receiver,
        # which would break whatever action triggered the nudge (e.g.
        # a message send or badge check).
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"unexpected_key": "some value"}
        mock_get_agent.return_value = mock_agent

        result = generate_nudge(self.user, progress_pct=90, badge=self.badge)

        self.assertIsNone(result)
        self.assertEqual(NudgeLog.objects.filter(user=self.user).count(), 0)

    @patch("ai_agents.factory.AgentFactory.get_agent")
    def test_fails_open_when_agent_returns_none(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.run.return_value = None
        mock_get_agent.return_value = mock_agent

        result = generate_nudge(self.user, progress_pct=90, badge=self.badge)

        self.assertIsNone(result)
