# TARGET PATH: engagement/utils.py
from datetime import timedelta

from django.utils import timezone

from .models import Badge, Mission, UserBadge, UserMissionProgress
from .signals import (
    badge_earned,
    badge_progress_updated,
    mission_completed,
    mission_progress_updated,
)

# Maps Badge.metric values to the matching UserEngagement field name.
# 'matches' has no direct counter on UserEngagement — conversation_count
# (incremented whenever a Connection is created) is the closest proxy.
# Revisit this if a cleaner "matches" counter gets added later.
METRIC_FIELD_MAP = {
    'matches': 'conversation_count',
    'messages_sent': 'messages_sent',
    'countries_connected': 'countries_connected',
    'groups_joined': 'groups_joined',
    'translations_used': 'translations_used',
}

# The prototype's 5 fixed badge emoji — Badge has no icon field, so this
# is keyed by badge_group (the value shared across a concept's 3 tiers).
BADGE_GROUP_ICONS = {
    'first_friend': '🥇',
    'social_butterfly': '💬',
    'global_explorer': '🌍',
    'group_champion': '🤝',
    'language_bridge': '🌐',
}

TIER_ORDER = {'bronze': 0, 'silver': 1, 'gold': 2}

# How close (0-100) a user must be to an un-earned badge/mission before
# badge_progress_updated / mission_progress_updated fires. Below this,
# progress updates happen silently with no signal — nobody wants a
# nudge at 5%.
NUDGE_THRESHOLD_PCT = 70


def check_and_award_badges(user):
    """
    Call this after any action that could cross a badge threshold —
    e.g. after a message is sent, a match is accepted, a group is joined.

    Confirmed callers (per each person's plan):
      - accounts/engagement (this app): profile actions
      - matching: after MatchRequest accepted, after join_group_view
      - chat: after send_message_view

    DESIGN PATTERN: Observer, via Django Signals. This function is the
    Subject — it announces "a badge was earned" via badge_earned.send()
    without knowing or caring what happens next. The actual Notification
    creation lives in engagement/signals.py as a separate Observer
    (@receiver function), fully decoupled from this function. Anyone
    needing to react to a badge being earned later (an email alert, an
    analytics log, etc.) just adds another receiver — this function
    never changes.

    Also fires badge_progress_updated for any un-earned badge whose
    progress has crossed NUDGE_THRESHOLD_PCT this call — a second,
    independent signal on the same loop, powering the Nudge agent.
    This does NOT change what this function returns or awards; it's
    purely an additional announcement using values already computed
    in the loop below.

    Returns the list of newly-earned Badge objects (empty list if none).
    """
    engagement = getattr(user, 'engagement', None)
    if engagement is None:
        return []

    already_earned_ids = set(
        UserBadge.objects.filter(user=user).values_list('badge_id', flat=True)
    )

    newly_earned = []

    for badge in Badge.objects.exclude(id__in=already_earned_ids):
        field_name = METRIC_FIELD_MAP.get(badge.metric)
        if not field_name:
            continue

        current_value = getattr(engagement, field_name, 0)
        if current_value >= badge.threshold:
            UserBadge.objects.create(user=user, badge=badge)
            badge_earned.send(sender=Badge, user=user, badge=badge)
            newly_earned.append(badge)
        elif badge.threshold:
            progress_pct = min(int(current_value / badge.threshold * 100), 100)
            if progress_pct >= NUDGE_THRESHOLD_PCT:
                badge_progress_updated.send(
                    sender=Badge, user=user, badge=badge, progress_pct=progress_pct,
                )

    return newly_earned


def get_badge_progress(user):
    """
    Collapses the 15 tiered Badge rows (5 concepts x Bronze/Silver/Gold)
    into 5 display rows for the profile page, matching the prototype's
    layout — one row per badge_group, showing the highest tier already
    earned plus progress toward the next tier (or "maxed out" at Gold).

    Returns a list of dicts:
      {
        'badge_group': str,
        'icon': str,
        'display_badge': Badge,      # whichever tier to show name/desc for
        'highest_earned': Badge | None,
        'is_earned': bool,           # at least Bronze earned
        'is_maxed': bool,            # Gold already earned
        'current_value': int,        # user's raw counter for this metric
        'target': int,               # next_tier's threshold (or maxed tier's)
        'pct': int,                  # 0-100 progress toward next_tier
      }
    """
    engagement = getattr(user, 'engagement', None)
    earned_badge_ids = set(
        UserBadge.objects.filter(user=user).values_list('badge_id', flat=True)
    )

    groups = {}
    for badge in Badge.objects.all():
        groups.setdefault(badge.badge_group, []).append(badge)

    result = []
    for group_key, badges in groups.items():
        badges_sorted = sorted(badges, key=lambda b: TIER_ORDER.get(b.tier, 0))
        earned_in_group = [b for b in badges_sorted if b.id in earned_badge_ids]
        next_tier = next((b for b in badges_sorted if b.id not in earned_badge_ids), None)

        highest_earned = earned_in_group[-1] if earned_in_group else None
        display_badge = next_tier or highest_earned  # falls back to Gold if maxed

        field_name = METRIC_FIELD_MAP.get(display_badge.metric) if display_badge else None
        current_value = getattr(engagement, field_name, 0) if (engagement and field_name) else 0

        target = next_tier.threshold if next_tier else (highest_earned.threshold if highest_earned else 1)
        pct = min(int(current_value / target * 100), 100) if target else 0

        result.append({
            'badge_group': group_key,
            'icon': BADGE_GROUP_ICONS.get(group_key, '🏅'),
            'display_badge': display_badge,
            'highest_earned': highest_earned,
            'is_earned': highest_earned is not None,
            'is_maxed': next_tier is None,
            'current_value': current_value,
            'target': target,
            'pct': pct,
        })

    return result


# ---------------------------------------------------------------------
# MISSIONS
#
# IMPORTANT: as of this build, nothing in matching/chat calls
# record_mission_progress() yet — those apps are still placeholder
# stubs (see social/matching/chat/views.py). This is the engine,
# ready for those real views to call once built. Until then,
# get_mission_progress() will correctly show 0 progress for everyone,
# because that's the true state of the data — not a display bug.
# ---------------------------------------------------------------------

def _current_period_start(mission):
    today = timezone.now().date()
    if mission.frequency == 'daily':
        return today
    # weekly — start of the current week (Monday)
    return today - timedelta(days=today.weekday())


def record_mission_progress(user, mission_key, amount=1):
    """
    Call this after a real action happens that should count toward a
    Mission (e.g. after send_message_view creates a Message, after
    join_group_view succeeds). Increments progress for the current
    period, creating the row if needed, and marks completed_at once
    the target is reached. No-ops quietly if the Mission doesn't exist
    (e.g. not seeded yet) or is already completed this period.

    Fires exactly one signal per call that actually changes progress:
    mission_completed if this call finished it, otherwise
    mission_progress_updated (used by the Nudge agent) with the
    current progress_pct — regardless of whether that pct has crossed
    NUDGE_THRESHOLD_PCT. The threshold gate lives in the Nudge
    receiver/service, not here, to keep this function's only job as
    "update progress and announce the new state."
    """
    try:
        mission = Mission.objects.get(key=mission_key)
    except Mission.DoesNotExist:
        return None

    period_start = _current_period_start(mission)

    progress_row, _ = UserMissionProgress.objects.get_or_create(
        user=user, mission=mission, period_start=period_start,
        defaults={'progress': 0},
    )

    if progress_row.completed_at:
        return progress_row  # already done for this period

    progress_row.progress = min(progress_row.progress + amount, mission.target)
    just_completed = False
    if progress_row.progress >= mission.target:
        progress_row.completed_at = timezone.now()
        just_completed = True
    progress_row.save()

    if just_completed:
        mission_completed.send(sender=Mission, user=user, mission=mission)
    elif mission.target:
        progress_pct = min(int(progress_row.progress / mission.target * 100), 100)
        mission_progress_updated.send(
            sender=Mission, user=user, mission=mission, progress_pct=progress_pct,
        )

    return progress_row


def get_mission_progress(user):
    """
    Returns current-period progress for every seeded Mission, creating
    a zero-progress row on the fly if one doesn't exist yet — so the
    profile page always has something consistent to render.
    """
    missions = Mission.objects.select_related('linked_badge').all()
    result = []

    for mission in missions:
        period_start = _current_period_start(mission)
        progress_row, _ = UserMissionProgress.objects.get_or_create(
            user=user, mission=mission, period_start=period_start,
            defaults={'progress': 0},
        )
        pct = min(int(progress_row.progress / mission.target * 100), 100) if mission.target else 0

        result.append({
            'mission': mission,
            'progress': progress_row.progress,
            'target': mission.target,
            'pct': pct,
            'completed': bool(progress_row.completed_at),
        })

    return result
