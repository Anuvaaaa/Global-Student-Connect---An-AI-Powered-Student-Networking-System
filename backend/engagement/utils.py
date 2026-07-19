from .models import Badge, Notification, UserBadge

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


def check_and_award_badges(user):
    """
    Call this after any action that could cross a badge threshold —
    e.g. after a message is sent, a match is accepted, a group is joined.

    Confirmed callers (per each person's plan):
      - accounts/engagement (this app): profile actions
      - matching: after MatchRequest accepted, after join_group_view
      - chat: after send_message_view

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
            Notification.objects.create(
                user=user,
                type='badge',
                title='Badge unlocked 🏅',
                description=f'You earned {badge.name} ({badge.get_tier_display()})!',
                cta_label='View Badge',
                cta_href='/profile/',
            )
            newly_earned.append(badge)

    return newly_earned
