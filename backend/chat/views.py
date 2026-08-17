from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.timesince import timesince
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .forms import MessageForm
from .models import Conversation
from .utils import country_code_for, date_label_for, translate_message
from ai_agents.services.safety_pipeline import check_message
from engagement.models import UserEngagement
from engagement.utils import check_and_award_badges, record_mission_progress
from matching.models import GroupMember
from matching.utils import compute_compatibility_score, is_blocked_either_way
from ai_agents.models import SafetyFlag
from social.models import Interest, UserInterest


# =====================================================================
# IDENTITY DISPLAY — single source of truth for "what do we show for
# this user's name/avatar/university/country". Handles is_deleted the
# same way social/views.py already does (show "Deleted Student", not
# the real identity) so every place chat displays a person goes through
# this instead of duplicating the same is_deleted check four times.
#
# Note: computing initial from the ALREADY-anonymized name means a
# deleted user's avatar naturally becomes "D" with no extra branching —
# one code path handles both cases.
# =====================================================================
def _display_identity(user):
    profile = getattr(user, 'profile', None)

    if user.is_deleted:
        name = 'Deleted Student'
        country = None
        university_name = None
    else:
        name = profile.display_name if profile and profile.display_name else user.username
        country = profile.country if profile and profile.country else None
        university_name = user.university.name if user.university else None

    return {
        'name': name,
        'initial': name[0].upper() if name else '?',
        'country': country or 'Unknown',
        'country_code': country_code_for(country),
        'university': university_name or 'Unknown University',
    }


# =====================================================================
# INBOX — logic pulled into a helper so both the page load (inbox_view)
# and the live-refresh endpoint (inbox_poll_view) build the exact same
# data from the exact same rules. Keeps them from drifting apart.
# =====================================================================
def _build_inbox_items(user):
    # --- Direct (1:1) conversations — only ones with an ACTIVE connection.
    direct_convos = (
        Conversation.objects
        .filter(type='direct', connection__status='active')
        .filter(Q(connection__user_a=user) | Q(connection__user_b=user))
        .select_related('connection__user_a__profile', 'connection__user_b__profile')
    )

    # --- Group conversations — only groups this user hasn't left.
    active_group_ids = GroupMember.objects.filter(
        user=user, left_at__isnull=True
    ).values_list('group_id', flat=True)

    group_convos = (
        Conversation.objects
        .filter(type='group', group_id__in=active_group_ids)
        .select_related('group')
    )

    items = []

    for conv in direct_convos:
        other = conv.connection.user_b if conv.connection.user_a_id == user.id else conv.connection.user_a
        identity = _display_identity(other)
        last_msg = conv.messages.order_by('-sent_at').first()
        unread = conv.messages.filter(is_read=False).exclude(sender=user).count()

        items.append({
            'type': 'friend',
            'conversation_id': conv.id,
            'name': identity['name'],
            'initial': identity['initial'],
            'last_msg': last_msg.text if last_msg else 'Say hello 👋',
            'sent_at': last_msg.sent_at if last_msg else conv.created_at,
            'unread': unread,
        })

    for conv in group_convos:
        last_msg = conv.messages.select_related('sender').order_by('-sent_at').first()
        unread = conv.messages.filter(is_read=False).exclude(sender=user).count()

        if last_msg:
            sender_name = _display_identity(last_msg.sender)['name']
            preview = f'{sender_name}: {last_msg.text}'
        else:
            preview = 'No messages yet'

        items.append({
            'type': 'group',
            'conversation_id': conv.id,
            'name': conv.group.name,
            'initial': conv.group.name[0].upper() if conv.group.name else '?',
            'last_msg': preview,
            'sent_at': last_msg.sent_at if last_msg else conv.created_at,
            'unread': unread,
        })

    items.sort(key=lambda i: i['sent_at'], reverse=True)
    return items


@login_required
def inbox_view(request):
    items = _build_inbox_items(request.user)
    return render(request, 'chat/chat.html', {
        'active_page': 'chat',
        'conversations': items,
    })


@login_required
def inbox_poll_view(request):
    items = _build_inbox_items(request.user)

    payload = [{
        'type': item['type'],
        'conversation_id': item['conversation_id'],
        'name': item['name'],
        'initial': item['initial'],
        'last_msg': item['last_msg'],
        'sent_at_display': timesince(item['sent_at']) + ' ago',
        'unread': item['unread'],
    } for item in items]

    return JsonResponse({'ok': True, 'conversations': payload})


# =====================================================================
# SHARED ACCESS CHECK
# =====================================================================
def _check_conversation_access(request, conversation):
    if conversation.type == 'direct':
        connection = conversation.connection
        if connection is None:
            return {'ok': False, 'error': 'Invalid conversation', 'is_active': False, 'other_user': None}
        if connection.user_a_id != request.user.id and connection.user_b_id != request.user.id:
            return {'ok': False, 'error': 'Not a participant', 'is_active': False, 'other_user': None}

        other = connection.user_b if connection.user_a_id == request.user.id else connection.user_a
        if is_blocked_either_way(request.user, other):
            return {'ok': False, 'error': 'This user is blocked', 'is_active': False, 'other_user': other}

        return {'ok': True, 'error': None, 'is_active': connection.status == 'active', 'other_user': other}

    elif conversation.type == 'group':
        membership = GroupMember.objects.filter(group=conversation.group, user=request.user).first()
        if membership is None:
            return {'ok': False, 'error': 'Not a member of this group', 'is_active': False, 'other_user': None}

        return {'ok': True, 'error': None, 'is_active': membership.left_at is None, 'other_user': None}

    return {'ok': False, 'error': 'Invalid conversation type', 'is_active': False, 'other_user': None}


def _attach_date_labels(message_list):
    last_label = None
    for m in message_list:
        label = date_label_for(m['sent_at'])
        m['date_label'] = label
        m['show_separator'] = (label != last_label)
        last_label = label
    return last_label


# =====================================================================
# CONVERSATION — dispatches to direct or group based on Conversation.type
# =====================================================================
@login_required
@ensure_csrf_cookie
def conversation_view(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)

    if conversation.type == 'group':
        return group_conversation_view(request, conversation_id)

    access = _check_conversation_access(request, conversation)
    if not access['ok']:
        return redirect('chat:inbox')

    other = access['other_user']

    conversation.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)

    viewer_profile = getattr(request.user, 'profile', None)
    auto_translate_on = bool(viewer_profile and viewer_profile.auto_translate)
    target_language = (viewer_profile.translate_into if viewer_profile else None) or 'English'

    messages_qs = conversation.messages.select_related('sender').order_by('sent_at')
    message_list = []
    for msg in messages_qs:
        translated_text = None
        if auto_translate_on and msg.sender_id != request.user.id:
            translation = translate_message(msg, target_language, for_user=request.user)
            translated_text = translation.translated_text if translation else None

        message_list.append({
            'id': msg.id,
            'text': msg.text,
            'sent_at': msg.sent_at,
            'is_mine': msg.sender_id == request.user.id,
            'translated_text': translated_text,
        })

    last_date_label = _attach_date_labels(message_list)

    other_identity = _display_identity(other)

    my_interest_ids = set(UserInterest.objects.filter(user=request.user).values_list('interest_id', flat=True))
    other_interest_ids = set(UserInterest.objects.filter(user=other).values_list('interest_id', flat=True))
    shared_interest_names = list(
        Interest.objects.filter(id__in=(my_interest_ids & other_interest_ids)).values_list('name', flat=True)
    )

    context = {
        'active_page': 'chat',
        'conversation': conversation,
        'other_user': other,
        'other_name': other_identity['name'],
        'other_university': other_identity['university'],
        'other_country': other_identity['country'],
        'other_country_code': other_identity['country_code'],
        'shared_interests': shared_interest_names,
        'compat_score': compute_compatibility_score(request.user, other),
        'messages': message_list,
        'last_message_id': message_list[-1]['id'] if message_list else 0,
        'last_date_label': last_date_label,
        'auto_translate_on': auto_translate_on,
        'translate_into': target_language,
        'connection_active': access['is_active'],
    }
    return render(request, 'chat/converse.html', context)


# =====================================================================
# GROUP CONVERSATION
# =====================================================================
@login_required
@ensure_csrf_cookie
def group_conversation_view(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)
    if conversation.type != 'group':
        return conversation_view(request, conversation_id)

    access = _check_conversation_access(request, conversation)
    if not access['ok']:
        return redirect('chat:inbox')

    conversation.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)

    viewer_profile = getattr(request.user, 'profile', None)
    auto_translate_on = bool(viewer_profile and viewer_profile.auto_translate)
    target_language = (viewer_profile.translate_into if viewer_profile else None) or 'English'

    messages_qs = conversation.messages.select_related('sender').order_by('sent_at')
    message_list = []
    for msg in messages_qs:
        translated_text = None
        if auto_translate_on and msg.sender_id != request.user.id:
            translation = translate_message(msg, target_language, for_user=request.user)
            translated_text = translation.translated_text if translation else None

        sender_identity = _display_identity(msg.sender)
        message_list.append({
            'id': msg.id,
            'text': msg.text,
            'sent_at': msg.sent_at,
            'is_mine': msg.sender_id == request.user.id,
            'translated_text': translated_text,
            'sender_name': sender_identity['name'],
            'sender_country_code': sender_identity['country_code'],
        })

    last_date_label = _attach_date_labels(message_list)

    active_memberships = list(
        GroupMember.objects.filter(group=conversation.group, left_at__isnull=True)
        .select_related('user__profile', 'user__university')
    )

    other_members = []
    all_interest_sets = []
    for gm in active_memberships:
        # Interests stay real regardless of deletion status — only
        # IDENTITY (name/avatar/university/country) gets anonymized.
        # Keeping interests intact means "Shared Interests" still works
        # correctly for everyone else still in the group; a deleted
        # member's tastes aren't identifying on their own the way their
        # name/school/country would be.
        member_interest_ids = set(
            UserInterest.objects.filter(user=gm.user).values_list('interest_id', flat=True)
        )
        all_interest_sets.append(member_interest_ids)

        if gm.user_id == request.user.id:
            continue

        identity = _display_identity(gm.user)
        member_interest_names = list(
            Interest.objects.filter(id__in=member_interest_ids).values_list('name', flat=True)
        )
        member_profile = getattr(gm.user, 'profile', None)
        languages = 'Not specified' if gm.user.is_deleted else (
            ' · '.join(filter(None, [
                member_profile.primary_language if member_profile else None,
                member_profile.secondary_language if member_profile else None,
            ])) or 'Not specified'
        )

        other_members.append({
            'user_id': gm.user.id,
            'name': identity['name'],
            'first_name': identity['name'].split(' ')[0],
            'initial': identity['initial'],
            'university': identity['university'],
            'country': identity['country'],
            'country_code': identity['country_code'],
            'languages': languages,
            'interests': member_interest_names,
        })

    shared_group_interest_ids = set.intersection(*all_interest_sets) if all_interest_sets else set()
    shared_group_interests = list(
        Interest.objects.filter(id__in=shared_group_interest_ids).values_list('name', flat=True)
    )

    context = {
        'active_page': 'chat',
        'conversation': conversation,
        'group': conversation.group,
        'member_count': len(active_memberships),
        'other_members': other_members,
        'shared_group_interests': shared_group_interests,
        'messages': message_list,
        'last_message_id': message_list[-1]['id'] if message_list else 0,
        'last_date_label': last_date_label,
        'auto_translate_on': auto_translate_on,
        'translate_into': target_language,
        'connection_active': access['is_active'],
    }
    return render(request, 'chat/group_converse.html', context)


@login_required
@require_POST
def send_message_view(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)

    access = _check_conversation_access(request, conversation)
    if not access['ok']:
        return JsonResponse({'ok': False, 'error': access['error']}, status=403)

    if not access['is_active']:
        error = 'This conversation has ended' if conversation.type == 'direct' else 'You have left this group'
        return JsonResponse({'ok': False, 'error': error}, status=403)

    form = MessageForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'error': 'Message is empty or too long'}, status=400)

    safety_result = check_message(form.cleaned_data['text'])
    if safety_result['action'] == 'auto_block':
        # Rejected outright — never saved, never sent. Still logged as a
        # SafetyFlag so this isn't a total black box: without this, a
        # false positive (e.g. a joke misread as harassment) would leave
        # zero trace anywhere for an admin to catch or reverse.
        SafetyFlag.objects.create(
            user=request.user,
            message=None,
            blocked_text=form.cleaned_data['text'],
            severity=safety_result.get('severity', 'high'),
            category=safety_result.get('category', 'other'),
            ai_reasoning=safety_result.get('reasoning', ''),
            status='open',
        )
        return JsonResponse({'ok': False, 'error': 'Message blocked.'}, status=400)

    message = form.save(commit=False)
    message.conversation = conversation
    message.sender = request.user
    message.save()

    if safety_result['action'] == 'queue_human_review':
        # Message still sends, but a SafetyFlag surfaces it on the
        # moderation dashboard for a human to review. This is separate
        # from Report — most flags never become one; report stays null
        # unless this later corroborates an existing user-filed report.
        SafetyFlag.objects.create(
            user=request.user,
            message=message,
            severity=safety_result.get('severity', 'medium'),
            category=safety_result.get('category', 'other'),
            ai_reasoning=safety_result.get('reasoning', ''),
            status='open',
        )

    eng, _ = UserEngagement.objects.get_or_create(user=request.user)
    eng.messages_sent += 1
    eng.save()
    check_and_award_badges(request.user)
    record_mission_progress(request.user, 'send_20_messages')

    if conversation.type == 'direct' and access['other_user']:
        other_profile = getattr(access['other_user'], 'profile', None)
        if other_profile and other_profile.auto_translate:
            target = other_profile.translate_into or other_profile.primary_language or 'English'
            translate_message(message, target, for_user=access['other_user'])

    elif conversation.type == 'group':
        other_active_members = (
            GroupMember.objects.filter(group=conversation.group, left_at__isnull=True)
            .exclude(user=request.user)
            .select_related('user__profile')
        )
        for gm in other_active_members:
            member_profile = getattr(gm.user, 'profile', None)
            if member_profile and member_profile.auto_translate:
                target = member_profile.translate_into or member_profile.primary_language or 'English'
                translate_message(message, target, for_user=gm.user)

    # The sender here is always the currently logged-in user, who by
    # definition can't be a deleted account (deleted users are logged
    # out and can't authenticate) — no anonymization needed for this
    # response specifically.
    sender_profile = getattr(request.user, 'profile', None)
    response_data = {
        'ok': True,
        'message': {
            'id': message.id,
            'text': message.text,
            'sent_at': message.sent_at.strftime('%H:%M'),
            'sender_name': sender_profile.display_name if sender_profile and sender_profile.display_name else request.user.username,
        }
    }
    if safety_result.get('stage') == 'error_fallback':
        # Gemini was unreachable (quota exhausted, outage, etc.) — the
        # message still sent normally and skipped AI screening entirely.
        # This notice is purely informational for the sender; it doesn't
        # block or delay anything. Reuse the report button for anything
        # that actually needs a human's attention while this is down.
        response_data['safety_notice'] = (
            "Heads up: our safety agent is taking a quick nap 😴 — messages are "
            "sending normally, just without the AI check for now. If you get "
            "something that isn't okay, use the report button."
        )
    return JsonResponse(response_data)


@login_required
def poll_messages_view(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)

    access = _check_conversation_access(request, conversation)
    if not access['ok']:
        return JsonResponse({'ok': False, 'error': access['error']}, status=403)

    try:
        since_id = int(request.GET.get('since', 0))
    except (TypeError, ValueError):
        since_id = 0

    new_messages = (
        conversation.messages.select_related('sender')
        .filter(id__gt=since_id)
        .order_by('sent_at')
    )

    new_messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)

    viewer_profile = getattr(request.user, 'profile', None)
    auto_translate_on = bool(viewer_profile and viewer_profile.auto_translate)
    target_language = (viewer_profile.translate_into if viewer_profile else None) or 'English'

    payload = []
    for msg in new_messages:
        translated_text = None
        if auto_translate_on and msg.sender_id != request.user.id:
            translation = translate_message(msg, target_language, for_user=request.user)
            translated_text = translation.translated_text if translation else None

        sender_identity = _display_identity(msg.sender)
        payload.append({
            'id': msg.id,
            'text': msg.text,
            'sent_at': msg.sent_at.strftime('%H:%M'),
            'is_mine': msg.sender_id == request.user.id,
            'translated_text': translated_text,
            'sender_name': sender_identity['name'],
            'sender_country_code': sender_identity['country_code'],
        })

    return JsonResponse({
        'ok': True,
        'messages': payload,
        'connection_active': access['is_active'],
    })


@login_required
@require_POST
def translate_message_view(request, conversation_id, message_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)
    message = get_object_or_404(conversation.messages, id=message_id)

    profile = getattr(request.user, 'profile', None)
    target_language = (profile.translate_into if profile else None) \
        or (profile.primary_language if profile else None) \
        or 'English'

    translation = translate_message(message, target_language, for_user=request.user)
    if translation is None:
        return JsonResponse({'ok': False, 'error': 'Could not translate'}, status=400)

    return JsonResponse({'ok': True, 'translated_text': translation.translated_text})


@login_required
@require_POST
def end_chat_view(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)

    if conversation.type != 'direct' or conversation.connection is None:
        return JsonResponse({'ok': False, 'error': 'Invalid conversation'}, status=400)

    connection = conversation.connection
    if connection.user_a_id != request.user.id and connection.user_b_id != request.user.id:
        return JsonResponse({'ok': False, 'error': 'Not a participant'}, status=403)

    if connection.status == 'active':
        connection.status = 'ended'
        connection.ended_reason = 'manual_end'
        connection.ended_at = timezone.now()
        connection.save()

    return JsonResponse({'ok': True})


@login_required
@require_POST
def leave_group_view(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)

    if conversation.type != 'group' or conversation.group is None:
        return JsonResponse({'ok': False, 'error': 'Invalid conversation'}, status=400)

    membership = GroupMember.objects.filter(
        group=conversation.group, user=request.user, left_at__isnull=True
    ).first()

    if membership is None:
        return JsonResponse({'ok': False, 'error': 'You are not a member of this group'}, status=403)

    membership.left_at = timezone.now()
    membership.save()

    return JsonResponse({'ok': True})