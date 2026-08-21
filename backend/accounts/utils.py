from django.utils import timezone


def get_block_message(user, now):
    """
    Returns the sign-in block message for a banned or currently-suspended
    user, or None if they're clear to log in. `now` is passed in rather
    than read internally so this stays a pure function of its inputs —
    callers pass timezone.now() at the actual call site.

    Ban takes priority over suspension: a banned user sees the ban
    message even if a stale suspended_until value is still sitting on
    their row from before the ban was applied.
    """
    if user.is_banned:
        return (
            "Your account has been permanently banned for violating "
            "community guidelines."
        )

    if user.suspended_until and user.suspended_until > now:
        local_time = timezone.localtime(user.suspended_until)
        return (
            "Your account is suspended until "
            f"{local_time.strftime('%B %d, %Y at %H:%M')} "
            "for violating community guidelines."
        )

    return None
