# TARGET PATH: engagement/tests/tests.py
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from ..models import Badge, Mission, Notification, UserBadge, UserEngagement, UserMissionProgress
from ..utils import (
    NUDGE_THRESHOLD_PCT,
    check_and_award_badges,
    get_badge_progress,
    get_mission_progress,
    record_mission_progress,
)

User = get_user_model()


def _make_user(email="student@example.edu"):
    from accounts.models import University

    university, _ = University.objects.get_or_create(
        domain="example.edu", defaults={"name": "Example University"},
    )
    # User extends AbstractUser, so username is required and unique —
    # use email as the username to keep this helper collision-free
    # across multiple calls in the same test.
    return User.objects.create_user(
        username=email, email=email, google_id=f"gid-{email}",
        university=university, is_verified=True, password="testpass123",
    )


@override_settings(NUDGE_AGENT_ASYNC=False)
class CheckAndAwardBadgesTests(TestCase):
    """Normal input, boundary values, and unexpected input for badge awarding."""

    def setUp(self):
        self.user = _make_user()
        self.engagement = UserEngagement.objects.create(user=self.user, messages_sent=0)
        self.badge = Badge.objects.create(
            key="social_butterfly_gold", name="Social Butterfly", threshold=50,
            metric="messages_sent", tier="gold", badge_group="social_butterfly",
        )

    # --- normal input ---
    def test_no_badges_awarded_when_below_threshold(self):
        self.engagement.messages_sent = 10
        self.engagement.save()

        newly_earned = check_and_award_badges(self.user)

        self.assertEqual(newly_earned, [])
        self.assertFalse(UserBadge.objects.filter(user=self.user, badge=self.badge).exists())

    def test_badge_awarded_and_notification_created_when_threshold_crossed(self):
        self.engagement.messages_sent = 999
        self.engagement.save()

        newly_earned = check_and_award_badges(self.user)

        self.assertEqual(newly_earned, [self.badge])
        self.assertTrue(UserBadge.objects.filter(user=self.user, badge=self.badge).exists())
        self.assertTrue(
            Notification.objects.filter(user=self.user, type="badge").exists()
        )

    def test_already_earned_badge_is_not_re_awarded(self):
        UserBadge.objects.create(user=self.user, badge=self.badge)
        self.engagement.messages_sent = 999
        self.engagement.save()

        newly_earned = check_and_award_badges(self.user)

        self.assertEqual(newly_earned, [])
        self.assertEqual(UserBadge.objects.filter(user=self.user, badge=self.badge).count(), 1)

    # --- boundary values ---
    def test_badge_awarded_exactly_at_threshold(self):
        self.engagement.messages_sent = self.badge.threshold  # exactly 50, not 49 or 51
        self.engagement.save()

        newly_earned = check_and_award_badges(self.user)

        self.assertEqual(newly_earned, [self.badge])

    def test_no_badge_awarded_one_below_threshold(self):
        self.engagement.messages_sent = self.badge.threshold - 1
        self.engagement.save()

        newly_earned = check_and_award_badges(self.user)

        self.assertEqual(newly_earned, [])

    def test_badge_with_zero_threshold_is_awarded_immediately(self):
        # threshold=0 means current_value (always >= 0) satisfies the
        # award condition on the very first check, regardless of
        # engagement. Documents this rather than leaving it implicit —
        # a zero threshold isn't a real seeded value today, but nothing
        # currently guards against creating one.
        zero_threshold_badge = Badge.objects.create(
            key="zero_threshold", name="Instant Badge", threshold=0,
            metric="messages_sent", tier="bronze", badge_group="instant",
        )

        newly_earned = check_and_award_badges(self.user)

        self.assertIn(zero_threshold_badge, newly_earned)

    # --- unexpected input ---
    def test_user_with_no_engagement_row_returns_empty_list(self):
        bare_user = _make_user(email="no-engagement@example.edu")

        newly_earned = check_and_award_badges(bare_user)

        self.assertEqual(newly_earned, [])

    def test_matches_metric_resolves_via_conversation_count_field(self):
        # 'matches' is the one Badge.metric value with no identically-
        # named UserEngagement field — it maps to conversation_count
        # instead (see METRIC_FIELD_MAP's comment in utils.py). Confirm
        # that indirection actually resolves correctly end-to-end,
        # rather than assuming the mapping works.
        Badge.objects.create(
            key="matches_badge", name="Matchmaker", threshold=1,
            metric="matches", tier="bronze", badge_group="matches_group",
        )
        self.engagement.conversation_count = 5
        self.engagement.save()

        newly_earned = check_and_award_badges(self.user)

        self.assertTrue(any(b.key == "matches_badge" for b in newly_earned))

    # --- behavior: the badge_progress_updated -> Nudge signal chain ---
    @patch("ai_agents.services.nudge_service.generate_nudge")
    def test_nudge_signal_fires_exactly_at_progress_threshold(self, mock_generate_nudge):
        self.engagement.messages_sent = int(self.badge.threshold * NUDGE_THRESHOLD_PCT / 100)
        self.engagement.save()

        check_and_award_badges(self.user)

        mock_generate_nudge.assert_called_once()
        _, kwargs = mock_generate_nudge.call_args
        self.assertGreaterEqual(kwargs["progress_pct"], NUDGE_THRESHOLD_PCT)

    @patch("ai_agents.services.nudge_service.generate_nudge")
    def test_no_nudge_signal_one_point_below_progress_threshold(self, mock_generate_nudge):
        # One message short of crossing NUDGE_THRESHOLD_PCT.
        just_below_pct = NUDGE_THRESHOLD_PCT - 1
        self.engagement.messages_sent = int(self.badge.threshold * just_below_pct / 100)
        self.engagement.save()

        check_and_award_badges(self.user)

        mock_generate_nudge.assert_not_called()

    @patch("ai_agents.services.nudge_service.generate_nudge")
    def test_no_nudge_signal_below_progress_threshold(self, mock_generate_nudge):
        self.engagement.messages_sent = 10
        self.engagement.save()

        check_and_award_badges(self.user)

        mock_generate_nudge.assert_not_called()

    @patch("ai_agents.services.nudge_service.generate_nudge")
    def test_no_nudge_signal_when_badge_just_earned(self, mock_generate_nudge):
        # Crossing the threshold this call awards the badge outright —
        # badge_earned fires, not badge_progress_updated.
        self.engagement.messages_sent = 50
        self.engagement.save()

        check_and_award_badges(self.user)

        mock_generate_nudge.assert_not_called()


class GetBadgeProgressTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.engagement = UserEngagement.objects.create(user=self.user, messages_sent=25)
        self.bronze = Badge.objects.create(
            key="sb_bronze", name="Social Butterfly", threshold=10,
            metric="messages_sent", tier="bronze", badge_group="social_butterfly",
        )
        self.silver = Badge.objects.create(
            key="sb_silver", name="Social Butterfly", threshold=50,
            metric="messages_sent", tier="silver", badge_group="social_butterfly",
        )

    def test_progress_toward_next_unearned_tier(self):
        UserBadge.objects.create(user=self.user, badge=self.bronze)

        result = get_badge_progress(self.user)

        row = next(r for r in result if r["badge_group"] == "social_butterfly")
        self.assertTrue(row["is_earned"])
        self.assertFalse(row["is_maxed"])
        self.assertEqual(row["display_badge"], self.silver)
        self.assertEqual(row["pct"], 50)  # 25/50

    def test_not_earned_when_no_tier_earned_yet(self):
        result = get_badge_progress(self.user)

        row = next(r for r in result if r["badge_group"] == "social_butterfly")
        self.assertFalse(row["is_earned"])
        self.assertIsNone(row["highest_earned"])

    def test_is_maxed_when_top_tier_earned(self):
        UserBadge.objects.create(user=self.user, badge=self.bronze)
        UserBadge.objects.create(user=self.user, badge=self.silver)

        result = get_badge_progress(self.user)

        row = next(r for r in result if r["badge_group"] == "social_butterfly")
        self.assertTrue(row["is_maxed"])
        self.assertEqual(row["display_badge"], self.silver)

    def test_user_with_no_engagement_row_shows_zero_progress(self):
        bare_user = _make_user(email="no-engagement-progress@example.edu")

        result = get_badge_progress(bare_user)

        row = next(r for r in result if r["badge_group"] == "social_butterfly")
        self.assertEqual(row["current_value"], 0)
        self.assertEqual(row["pct"], 0)


@override_settings(NUDGE_AGENT_ASYNC=False)
class RecordMissionProgressTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.mission = Mission.objects.create(
            key="daily_chat", name="Send 3 messages", frequency="daily", target=3,
        )

    # --- normal input ---
    def test_increments_progress(self):
        record_mission_progress(self.user, "daily_chat", amount=1)

        row = UserMissionProgress.objects.get(user=self.user, mission=self.mission)
        self.assertEqual(row.progress, 1)
        self.assertIsNone(row.completed_at)

    def test_completing_mission_creates_notification(self):
        record_mission_progress(self.user, "daily_chat", amount=3)

        row = UserMissionProgress.objects.get(user=self.user, mission=self.mission)
        self.assertIsNotNone(row.completed_at)
        self.assertTrue(
            Notification.objects.filter(user=self.user, type="mission").exists()
        )

    def test_no_ops_once_already_completed_this_period(self):
        record_mission_progress(self.user, "daily_chat", amount=3)
        record_mission_progress(self.user, "daily_chat", amount=1)

        row = UserMissionProgress.objects.get(user=self.user, mission=self.mission)
        self.assertEqual(row.progress, 3)  # unchanged, not 4

    # --- boundary values ---
    def test_amount_exceeding_target_is_capped_not_overshot(self):
        record_mission_progress(self.user, "daily_chat", amount=999)

        row = UserMissionProgress.objects.get(user=self.user, mission=self.mission)
        self.assertEqual(row.progress, self.mission.target)

    def test_amount_zero_does_not_change_progress_or_complete(self):
        record_mission_progress(self.user, "daily_chat", amount=0)

        row = UserMissionProgress.objects.get(user=self.user, mission=self.mission)
        self.assertEqual(row.progress, 0)
        self.assertIsNone(row.completed_at)

    def test_mission_with_zero_target_does_not_crash(self):
        Mission.objects.create(key="zero_target", name="Broken mission", frequency="daily", target=0)

        # Should not raise (division-by-target guarded by `elif mission.target:`)
        result = record_mission_progress(self.user, "zero_target", amount=1)

        self.assertIsNotNone(result)

    # --- unexpected input ---
    def test_unknown_mission_key_returns_none(self):
        result = record_mission_progress(self.user, "does_not_exist", amount=1)
        self.assertIsNone(result)

    def test_empty_string_mission_key_returns_none(self):
        result = record_mission_progress(self.user, "", amount=1)
        self.assertIsNone(result)

    def test_none_mission_key_returns_none(self):
        result = record_mission_progress(self.user, None, amount=1)
        self.assertIsNone(result)

    # --- behavior: the mission_progress_updated -> Nudge signal chain ---
    @patch("ai_agents.services.nudge_service.generate_nudge")
    def test_progress_signal_triggers_nudge_without_completing(self, mock_generate_nudge):
        record_mission_progress(self.user, "daily_chat", amount=1)  # 1/3 = 33%

        mock_generate_nudge.assert_called_once()
        _, kwargs = mock_generate_nudge.call_args
        self.assertEqual(kwargs["progress_pct"], 33)
        self.assertEqual(kwargs["mission"], self.mission)

    @patch("ai_agents.services.nudge_service.generate_nudge")
    def test_no_progress_signal_fires_on_completion_call(self, mock_generate_nudge):
        # mission_completed fires instead of mission_progress_updated
        record_mission_progress(self.user, "daily_chat", amount=3)

        mock_generate_nudge.assert_not_called()


class GetMissionProgressTests(TestCase):
    def test_returns_zero_progress_row_for_seeded_mission_with_no_activity(self):
        user = _make_user()
        Mission.objects.create(key="weekly_group", name="Join a group", frequency="weekly", target=1)

        result = get_mission_progress(user)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["progress"], 0)
        self.assertEqual(result[0]["pct"], 0)
        self.assertFalse(result[0]["completed"])

    def test_no_missions_seeded_returns_empty_list(self):
        user = _make_user()

        result = get_mission_progress(user)

        self.assertEqual(result, [])


class NotificationsViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.client = Client()
        self.client.force_login(self.user)

    # --- normal input ---
    def test_notifications_grouped_by_date_label(self):
        today_notif = Notification.objects.create(
            user=self.user, type="system", title="Today notif",
        )
        old_notif = Notification.objects.create(
            user=self.user, type="system", title="Old notif",
        )
        old_notif.created_at = timezone.now() - timedelta(days=5)
        old_notif.save(update_fields=["created_at"])

        response = self.client.get("/notifications/")

        self.assertEqual(response.status_code, 200)
        labels = {row["notif"].id: row["date_label"] for row in response.context["notif_list"]}
        self.assertEqual(labels[today_notif.id], "Today")
        self.assertEqual(labels[old_notif.id], "Earlier")

    def test_mark_notification_read(self):
        notif = Notification.objects.create(user=self.user, type="system", title="x", is_read=False)

        self.client.post(f"/notifications/{notif.id}/read/")

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_open_notification_marks_read_and_redirects_to_cta(self):
        notif = Notification.objects.create(
            user=self.user, type="badge", title="x", cta_href="/profile/",
        )

        response = self.client.get(f"/notifications/{notif.id}/open/")

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
        self.assertRedirects(response, "/profile/", fetch_redirect_response=False)

    def test_open_notification_without_cta_redirects_to_notifications(self):
        notif = Notification.objects.create(user=self.user, type="system", title="x", cta_href=None)

        response = self.client.get(f"/notifications/{notif.id}/open/")

        self.assertRedirects(response, "/notifications/", fetch_redirect_response=False)

    def test_mark_all_read(self):
        Notification.objects.create(user=self.user, type="system", title="a", is_read=False)
        Notification.objects.create(user=self.user, type="system", title="b", is_read=False)

        self.client.post("/notifications/mark-all-read/")

        self.assertFalse(Notification.objects.filter(user=self.user, is_read=False).exists())

    # --- boundary: empty state ---
    def test_notifications_page_with_no_notifications(self):
        response = self.client.get("/notifications/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["notif_list"]), [])

    def test_mark_all_read_with_no_notifications_does_not_error(self):
        response = self.client.post("/notifications/mark-all-read/")

        self.assertEqual(response.status_code, 302)

    # --- unexpected input ---
    def test_mark_notification_read_nonexistent_id_returns_404(self):
        response = self.client.post("/notifications/999999/read/")

        self.assertEqual(response.status_code, 404)

    def test_open_notification_nonexistent_id_returns_404(self):
        response = self.client.get("/notifications/999999/open/")

        self.assertEqual(response.status_code, 404)

    def test_cannot_mark_another_users_notification_read(self):
        other_user = _make_user(email="other@example.edu")
        notif = Notification.objects.create(user=other_user, type="system", title="x")

        response = self.client.post(f"/notifications/{notif.id}/read/")

        self.assertEqual(response.status_code, 404)
        notif.refresh_from_db()
        self.assertFalse(notif.is_read)

    # --- behavior: authentication required ---
    def test_notifications_page_requires_login(self):
        anonymous_client = Client()

        response = anonymous_client.get("/notifications/")

        self.assertNotEqual(response.status_code, 200)
        self.assertIn(response.status_code, (302, 403))
