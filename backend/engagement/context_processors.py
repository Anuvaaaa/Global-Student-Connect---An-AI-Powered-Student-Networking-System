def unread_notifications_count(request):
    """
    Makes {{ unread_notif_count }} available in every template, on every
    page, without each view needing to fetch it individually — that's
    the whole point of a context processor: one place to compute
    something every page needs, instead of repeating it in
    profile_view, notifications_view, and every future view too.

    Replaces base.html's old localStorage.getItem('unreadNotifs')
    fake count with a real one from the database.
    """
    if request.user.is_authenticated:
        count = request.user.notifications.filter(is_read=False).count()
    else:
        count = 0

    return {'unread_notif_count': count}
