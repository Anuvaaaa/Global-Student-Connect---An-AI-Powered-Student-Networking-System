"""
DESIGN PATTERN: Observer, implemented via Django Signals.

Django Signals ARE Django's own built-in Observer pattern — a Signal is
the Subject, and any function connected with @receiver is an Observer,
automatically notified when the signal fires. This isn't a pattern
bolted onto Django from the outside; it's using the framework's own
idiom correctly.

badge_earned is sent from engagement/utils.py's check_and_award_badges()
whenever a user crosses a badge threshold. That function has no idea
what happens after it sends the signal — it just announces the event.
The receiver below is the Observer: it reacts by creating a
Notification. If something else should also happen when a badge is
earned later (an email, an analytics log, an achievement-unlock sound
on the frontend), a new @receiver function gets added here — the
Subject (check_and_award_badges) never needs to change.
"""

from django.dispatch import Signal, receiver

# Sent whenever a user earns a new Badge.
# Providing args: user (accounts.User), badge (engagement.Badge)
badge_earned = Signal()

# Sent whenever a user completes a Mission for the current period.
# Providing args: user (accounts.User), mission (engagement.Mission)
mission_completed = Signal()


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
