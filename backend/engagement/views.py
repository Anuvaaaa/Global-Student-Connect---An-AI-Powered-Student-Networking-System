from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def notifications_view(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)

    # Real date grouping from created_at, replacing the prototype's
    # faked "2h ago" / "Yesterday" strings baked into seed data.
    notif_list = []
    for notif in notifications:
        notif_date = timezone.localtime(notif.created_at).date()
        if notif_date == today:
            label = 'Today'
        elif notif_date == yesterday:
            label = 'Yesterday'
        else:
            label = 'Earlier'
        notif_list.append({'notif': notif, 'date_label': label})

    return render(request, 'engagement/notifications.html', {
        'active_page': 'notifications',
        'notif_list': notif_list,
    })


@login_required
@require_POST
def mark_notification_read_view(request, notification_id):
    """
    Card-body click (not the CTA) — marks read, stays on the page.
    Matches the prototype's markRead(id) on the card div.
    """
    notif = get_object_or_404(Notification, id=notification_id, user=request.user)
    notif.is_read = True
    notif.save(update_fields=['is_read'])
    return redirect('engagement:notifications')


@login_required
def open_notification_view(request, notification_id):
    """
    CTA click — marks read AND navigates to cta_href. A plain GET
    since it's a real <a> link, not a form submit (matches the
    prototype's cta.onclick doing both markRead() and navigation).
    """
    notif = get_object_or_404(Notification, id=notification_id, user=request.user)
    notif.is_read = True
    notif.save(update_fields=['is_read'])
    if notif.cta_href:
        return redirect(notif.cta_href)
    return redirect('engagement:notifications')


@login_required
@require_POST
def mark_all_read_view(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect('engagement:notifications')
