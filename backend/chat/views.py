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
from engagement.models import UserEngagement
from engagement.utils import check_and_award_badges
from matching.models import GroupMember
from matching.utils import compute_compatibility_score, is_blocked_either_way
from social.models import Interest, UserInterest


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
        other_profile = getattr(other, 'profile', None)
        last_msg = conv.messages.order_by('-sent_at').first()
        unread = conv.messages.filter(is_read=False).exclude(sender=user).count()

        display_name = other_profile.display_name if other_profile and other_profile.display_name else other.username

        items.append({
            'type': 'friend',
            'conversation_id': conv.id,
            'name': display_name,
            'initial': display_name[0].upper(),
            'last_msg': last_msg.text if last_msg else 'Say hello 👋',
            'sent_at': last_msg.sent_at if last_msg else conv.created_at,
            'unread': unread,
        })

    for conv in group_convos:
        last_msg = conv.messages.select_related('sender__profile').order_by('-sent_at').first()
        unread = conv.messages.filter(is_read=False).exclude(sender=user).count()

        if last_msg:
            sender_profile = getattr(last_msg.sender, 'profile', None)
            sender_name = sender_profile.display_name if sender_profile else last_msg.sender.username
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

    other_profile = getattr(other, 'profile', None)
    other_country = other_profile.country if other_profile and other_profile.country else None

    my_interest_ids = set(UserInterest.objects.filter(user=request.user).values_list('interest_id', flat=True))
    other_interest_ids = set(UserInterest.objects.filter(user=other).values_list('interest_id', flat=True))
    shared_interest_names = list(
        Interest.objects.filter(id__in=(my_interest_ids & other_interest_ids)).values_list('name', flat=True)
    )

    context = {
        'active_page': 'chat',
        'conversation': conversation,
        'other_user': other,
        'other_name': other_profile.display_name if other_profile and other_profile.display_name else other.username,
        'other_university': other.university.name if other.university else 'Unknown University',
        'other_country': other_country or 'Unknown',
        'other_country_code': country_code_for(other_country),
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

    messages_qs = conversation.messages.select_related('sender__profile').order_by('sent_at')
    message_list = []
    for msg in messages_qs:
        translated_text = None
        if auto_translate_on and msg.sender_id != request.user.id:
            translation = translate_message(msg, target_language, for_user=request.user)
            translated_text = translation.translated_text if translation else None

        sender_profile = getattr(msg.sender, 'profile', None)
        message_list.append({
            'id': msg.id,
            'text': msg.text,
            'sent_at': msg.sent_at,
            'is_mine': msg.sender_id == request.user.id,
            'translated_text': translated_text,
            'sender_name': sender_profile.display_name if sender_profile and sender_profile.display_name else msg.sender.username,
            'sender_country_code': country_code_for(sender_profile.country if sender_profile else None),
        })

    last_date_label = _attach_date_labels(message_list)

    active_memberships = list(
        GroupMember.objects.filter(group=conversation.group, left_at__isnull=True)
        .select_related('user__profile', 'user__university')
    )

    other_members = []
    all_interest_sets = []
    for gm in active_memberships:
        member_interest_ids = set(
            UserInterest.objects.filter(user=gm.user).values_list('interest_id', flat=True)
        )
        all_interest_sets.append(member_interest_ids)

        if gm.user_id == request.user.id:
            continue

        member_profile = getattr(gm.user, 'profile', None)
        member_interest_names = list(
            Interest.objects.filter(id__in=member_interest_ids).values_list('name', flat=True)
        )
        languages = ' · '.join(filter(None, [
            member_profile.primary_language if member_profile else None,
            member_profile.secondary_language if member_profile else None,
        ])) or 'Not specified'

        display_name = member_profile.display_name if member_profile and member_profile.display_name else gm.user.username
        member_country = member_profile.country if member_profile and member_profile.country else None

        other_members.append({
            'user_id': gm.user.id,
            'name': display_name,
            'first_name': display_name.split(' ')[0],
            'initial': display_name[0].upper(),
            'university': gm.user.university.name if gm.user.university else 'Unknown University',
            'country': member_country or 'Unknown',
            'country_code': country_code_for(member_country),
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

    message = form.save(commit=False)
    message.conversation = conversation
    message.sender = request.user
    message.save()

    eng, _ = UserEngagement.objects.get_or_create(user=request.user)
    eng.messages_sent += 1
    eng.save()
    check_and_award_badges(request.user)

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

    sender_profile = getattr(request.user, 'profile', None)
    return JsonResponse({
        'ok': True,
        'message': {
            'id': message.id,
            'text': message.text,
            'sent_at': message.sent_at.strftime('%H:%M'),
            'sender_name': sender_profile.display_name if sender_profile and sender_profile.display_name else request.user.username,
        }
    })


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
        conversation.messages.select_related('sender__profile')
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

        sender_profile = getattr(msg.sender, 'profile', None)
        payload.append({
            'id': msg.id,
            'text': msg.text,
            'sent_at': msg.sent_at.strftime('%H:%M'),
            'is_mine': msg.sender_id == request.user.id,
            'translated_text': translated_text,
            'sender_name': sender_profile.display_name if sender_profile and sender_profile.display_name else msg.sender.username,
            'sender_country_code': country_code_for(sender_profile.country if sender_profile else None),
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
