"""
moderation/views.py

Minimal version of Step 8 from the matching/chat/moderation breakdown —
built now (ahead of schedule) only because converse.html's Report button
needs a real endpoint to submit to. group_converse.html will reuse this
same view once it's built, passing reported_user_id explicitly since a
group has more than one other person to report.
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from .models import Report
from chat.models import Conversation


@login_required
@require_POST
def report_user_view(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)

    reason = request.POST.get('reason')
    if not reason:
        return JsonResponse({'ok': False, 'error': 'Reason is required'}, status=400)

    reported_user_id = request.POST.get('reported_user_id')
    if reported_user_id:
        from accounts.models import User
        reported_user = get_object_or_404(User, id=reported_user_id)
    elif conversation.type == 'direct' and conversation.connection:
        c = conversation.connection
        reported_user = c.user_b if c.user_a_id == request.user.id else c.user_a
    else:
        # Group conversation with no explicit target — group_converse.html
        # will always send reported_user_id once it's built, so this only
        # fires if something calls this endpoint incorrectly.
        return JsonResponse({'ok': False, 'error': 'Could not determine who to report'}, status=400)

    Report.objects.create(
        reporter=request.user,
        reported_user=reported_user,
        reason=reason,
        context_conversation=conversation,
    )

    return JsonResponse({'ok': True})
