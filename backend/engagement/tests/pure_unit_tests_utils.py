# TARGET PATH: engagement/tests/test_utils.py
"""
Pure unit tests for engagement/utils.py.

Most of this file's functions (check_and_award_badges, get_badge_progress,
record_mission_progress, get_mission_progress) query Badge/UserBadge/
Mission/UserMissionProgress directly, so they can't be tested without a
database — those need integration tests, not unit tests, and aren't
included here.

What IS pure: _current_period_start() (once the current date is fixed via
mock) and _progress_pct(), the percentage helper factored out of the four
places above that used to duplicate this math inline. See the docstring
note in utils.py for that refactor.
"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from engagement.models import Badge, Mission
from engagement.utils import (
    BADGE_GROUP_ICONS,
    METRIC_FIELD_MAP,
    NUDGE_THRESHOLD_PCT,
    TIER_ORDER,
    _current_period_start,
    _progress_pct,
)


# ---------------------------------------------------------------------------
# Pure unit tests from here
# ---------------------------------------------------------------------------

class ProgressPctTests(TestCase):

    def test_halfway_progress(self):
        # normal input
        self.assertEqual(_progress_pct(50, 100), 50)

    def test_zero_progress_is_boundary_minimum(self):
        # boundary condition: minimum value
        self.assertEqual(_progress_pct(0, 100), 0)

    def test_exact_target_is_hundred_percent(self):
        # boundary condition: current equals target exactly
        self.assertEqual(_progress_pct(100, 100), 100)

    def test_overshoot_is_capped_at_hundred(self):
        # boundary condition: current exceeds target (max cap)
        self.assertEqual(_progress_pct(150, 100), 100)

    def test_zero_target_returns_zero_not_error(self):
        # unexpected input: would otherwise raise ZeroDivisionError
        self.assertEqual(_progress_pct(10, 0), 0)

    def test_none_target_returns_zero_not_error(self):
        # unexpected input: target missing entirely
        self.assertEqual(_progress_pct(10, None), 0)

    def test_negative_current_value(self):
        # negative input: documents actual behavior rather than assuming
        # a floor of 0 — utils.py has no lower clamp, only an upper one
        self.assertEqual(_progress_pct(-20, 100), -20)

    def test_rounds_down_not_to_nearest(self):
        # behavior: int() truncates rather than rounding, so 1/3 -> 33, not 33.3 or 34
        self.assertEqual(_progress_pct(1, 3), 33)


class CurrentPeriodStartTests(TestCase):

    def test_daily_mission_returns_today_regardless_of_weekday(self):
        # normal input
        fake_mission = SimpleNamespace(frequency="daily")
        fixed_now = datetime(2026, 8, 19)  # a Wednesday
        with patch("engagement.utils.timezone.now") as mock_now:
            mock_now.return_value = fixed_now
            result = _current_period_start(fake_mission)
        self.assertEqual(result, date(2026, 8, 19))

    def test_weekly_mission_on_monday_is_boundary_start_of_week(self):
        # boundary condition: weekday() == 0, start of its own week
        fake_mission = SimpleNamespace(frequency="weekly")
        fixed_now = datetime(2026, 8, 17)  # a Monday
        with patch("engagement.utils.timezone.now") as mock_now:
            mock_now.return_value = fixed_now
            result = _current_period_start(fake_mission)
        self.assertEqual(result, date(2026, 8, 17))

    def test_weekly_mission_on_sunday_is_boundary_end_of_week(self):
        # boundary condition: weekday() == 6, furthest day from Monday
        fake_mission = SimpleNamespace(frequency="weekly")
        fixed_now = datetime(2026, 8, 23)  # a Sunday
        with patch("engagement.utils.timezone.now") as mock_now:
            mock_now.return_value = fixed_now
            result = _current_period_start(fake_mission)
        self.assertEqual(result, date(2026, 8, 17))  # preceding Monday

    def test_weekly_mission_midweek_rolls_back_to_monday(self):
        # normal input
        fake_mission = SimpleNamespace(frequency="weekly")
        fixed_now = datetime(2026, 8, 19)  # a Wednesday
        with patch("engagement.utils.timezone.now") as mock_now:
            mock_now.return_value = fixed_now
            result = _current_period_start(fake_mission)
        self.assertEqual(result, date(2026, 8, 17))

    def test_unrecognized_frequency_falls_back_to_weekly_math(self):
        # unexpected input: only "daily" is special-cased; anything else
        # (typo, unseeded value) silently takes the weekly branch
        fake_mission = SimpleNamespace(frequency="monthly")
        fixed_now = datetime(2026, 8, 19)  # a Wednesday
        with patch("engagement.utils.timezone.now") as mock_now:
            mock_now.return_value = fixed_now
            result = _current_period_start(fake_mission)
        self.assertEqual(result, date(2026, 8, 17))


class ConstantConsistencyTests(TestCase):
    """
    Sanity checks that the hand-maintained lookup dicts in utils.py stay in
    sync with the model's own choice lists. These import the model classes
    but never touch the database — Badge.METRIC_CHOICES is a class-level
    attribute, not a query.
    """

    def test_metric_field_map_covers_every_badge_metric_choice(self):
        # unexpected input guard: a Badge.metric value with no mapped
        # UserEngagement field would silently no-op in check_and_award_badges
        metric_values = [choice[0] for choice in Badge.METRIC_CHOICES]
        for metric in metric_values:
            self.assertIn(metric, METRIC_FIELD_MAP)

    def test_tier_order_covers_every_badge_tier_choice(self):
        # unexpected input guard: an unmapped tier defaults to 0 in the
        # sort key, silently mis-ordering badges within a group
        tier_values = [choice[0] for choice in Badge.TIER_CHOICES]
        for tier in tier_values:
            self.assertIn(tier, TIER_ORDER)

    def test_nudge_threshold_is_within_valid_percentage_range(self):
        # boundary condition: constant sanity check
        self.assertGreaterEqual(NUDGE_THRESHOLD_PCT, 0)
        self.assertLessEqual(NUDGE_THRESHOLD_PCT, 100)

    def test_badge_group_icons_values_are_non_empty_strings(self):
        # normal input: every configured icon is a real, non-blank string
        for group_key, icon in BADGE_GROUP_ICONS.items():
            self.assertIsInstance(icon, str)
            self.assertGreater(len(icon), 0)
