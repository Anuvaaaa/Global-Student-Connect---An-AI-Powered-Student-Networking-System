# TARGET PATH: engagement/signals.py
"""
DESIGN PATTERN: Observer, implemented via Django Signals.

Django Signals ARE Django's own built-in Observer pattern — a Signal is
the Subject, and any function connected with @receiver is an Observer,
automatically notified when the signal fires. This isn't a pattern
bolted onto Django from the outside; it's using the framework's own
idiom correctly.

badge_earned / mission_completed are sent from engagement/utils.py's
check_and_award_badges() / record_mission_progress() whenever a user
crosses a badge threshold or finishes a mission for the current
period. Those functions have no idea what happens after they send a
signal — they just announce the event.

badge_progress_updated / mission_progress_updated are the NEW signals
that power the Nudge agent (added alongside the existing two, not
replacing them). They fire on every progress update that ISN'T yet a
completion — see engagement/utils.py for exactly where. This is a
second, independent Observer relationship on the same Subject
functions: check_and_award_badges() / record_mission_progress() never
needed to change their own logic to support Nudge, they only gained
one additional signal.send() call each.
"""

import threading

from django.conf import settings
from django.db import close_old_connections
from django.dispatch import Signal, receiver

# Sent whenever a user earns a new Badge.
# Providing args: user (accounts.User), badge (engagement.Badge)
badge_earned = Signal()

# Sent whenever a user completes a Mission for the current period.
# Providing args: user (accounts.User), mission (engagement.Mission)
mission_completed = Signal()

# Sent whenever a user's progress toward an un-earned Badge is
# recalculated AND has crossed the "close" threshold (see
# NUDGE_THRESHOLD_PCT in utils.py). Never sent for badges already
# earned this call — that's badge_earned's job instead.
# Providing args: user (accounts.User), badge (engagement.Badge),
#                 progress_pct (int, 0-100)
badge_progress_updated = Signal()

# Sent whenever UserMissionProgress.progress is updated and the
# mission was NOT completed by this call (mission_completed fires
# instead in that case).
# Providing args: user (accounts.User), mission (engagement.Mission),
#                 progress_pct (int, 0-100)
mission_progress_updated = Signal()


@receiver(badge_earned)
def create_badge_notification(sender, user, badge, **kwargs):
    # Local import avoids a circular import at Django app-loading time
    # (this module gets imported from apps.py's ready(), before all
    # models are necessarily loaded).
    from .models import Notification

    Notification.objects.create(
        user=user,
        type='badge',
        title='Badge unlocked 🏅',
        description=f'You earned {badge.name} ({badge.get_tier_display()})!',
        cta_label='View Badge',
        cta_href='/profile/',
    )


@receiver(mission_completed)
def create_mission_notification(sender, user, mission, **kwargs):
    from .models import Notification

    Notification.objects.create(
        user=user,
        type='mission',
        title='Mission complete 🎯',
        description=f'You finished "{mission.name}" — keep going!',
    )


def _run_nudge_in_background(**kwargs):
    """
    Runs generate_nudge() off the request thread so a Gemini call never
    blocks the HTTP response that triggered it (e.g. send_message_view).
    Nudge never gates whether the triggering action succeeds — unlike
    Safety, which must block because it decides whether a message sends
    at all — so there's no reason for the user to wait on it.

    NUDGE_AGENT_ASYNC (settings.py, defaults True) exists so tests can
    disable threading and assert on generate_nudge's effects
    synchronously and deterministically — see engagement/tests.py,
    which sets NUDGE_AGENT_ASYNC=False via @override_settings on the
    test classes that check this signal fires.
    """
    from ai_agents.services.nudge_service import generate_nudge

    if not getattr(settings, "NUDGE_AGENT_ASYNC", True):
        generate_nudge(**kwargs)
        return

    def _wrapper():
        try:
            generate_nudge(**kwargs)
        finally:
            # Each thread gets its own DB connection lazily on first
            # query; without this it's never returned, and connections
            # accumulate over the life of the dev/prod server process.
            close_old_connections()

    threading.Thread(target=_wrapper, daemon=True).start()


@receiver(badge_progress_updated)
def nudge_on_badge_progress(sender, user, badge, progress_pct, **kwargs):
    """
    Second Observer on the same badge-progress event. Purely additive —
    generates an LLM nudge message via the Nudge agent and logs it.
    Does not affect badge-award logic in any way; if this fails or is
    skipped (rate-limited, Gemini unavailable), badge awarding is
    completely unaffected.
    """
    _run_nudge_in_background(user=user, progress_pct=progress_pct, badge=badge)


@receiver(mission_progress_updated)
def nudge_on_mission_progress(sender, user, mission, progress_pct, **kwargs):
    """Same as nudge_on_badge_progress, for missions instead of badges."""
    _run_nudge_in_background(user=user, progress_pct=progress_pct, mission=mission)
