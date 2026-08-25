"""
matching/views.py

Covers Steps 2-4 of the matching slice:
  - connect_view              (Step 2 — main page)
  - find_friend_view          (Step 2 — replaces the prototype's fake
                                "Find a Friend" animation with a real
                                MatchRequest)
  - match_status_view         (Step 2 — polling endpoint so the
                                "waiting" screen can find out for real
                                whether the other person accepted)
  - cancel_match_request_view (Step 2 — "Cancel Request" button)
  - incoming_requests_view    (Step 2 — powers the incoming-matches
                                badge/modal)
  - accept_match_view         (Step 2)
  - decline_match_view        (Step 2)
  - join_group_view           (Step 3 — instant, no MatchRequest)
  - block_user_view           (Step 4 — the cascade logic)

NOTE ON THE PROTOTYPE'S FAKE TIMERS:
connect.html's JS auto-resolves a match after a few seconds with
Math.random(). That was only possible because there was no second real
person. Here, a MatchRequest genuinely sits at status='pending' until
the recipient visits their own incoming-requests panel and clicks
Accept/Decline. The "waiting" screen on the requester's side now polls
match_status_view every couple seconds via fetch() instead of running
a fake countdown.
"""

import json
from collections import Counter
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .models import MatchRequest, Connection, Block, StudentGroup, GroupMember
from .utils import is_blocked_either_way, compute_compatibility_score, get_best_match, get_open_group_for
from chat.models import Conversation
from engagement.models import Notification, UserEngagement
from engagement.utils import check_and_award_badges, record_mission_progress  # Person A's function — confirm signature
from social.models import UserInterest

GROUP_MAX_MEMBERS = 4  # prototype's groups were 3-4 people

# Same mapping used in accounts/templates/accounts/profile_setup.html — kept
# in sync manually since interest emojis aren't stored on the Interest model.
INTEREST_EMOJI = {
    "Music": "🎵",
    "Travel": "✈️",
    "Reading": "📚",
    "Photography": "📸",
    "Art & Design": "🎨",
    "Cricket": "🏏",
    "Football": "⚽",
    "Badminton": "🏸",
    "Cooking": "🍳",
    "Coding": "💻",
    "Movies & TV": "🎬",
    "Gaming": "🎮",
}


def _get_or_create_engagement(user):
    engagement, _ = UserEngagement.objects.get_or_create(user=user)
    return engagement


# =====================================================================
# STEP 2 — MAIN PAGE
# =====================================================================
def _get_todays_stats():
    """
    Real numbers behind the stats row, computed from today's data instead
    of the prototype's fake animated counters. Cheap enough for a small
    student-project dataset; if this ever needs to run at real scale,
    swap it for a scheduled aggregate instead of computing on every
    page load.
    """
    from collections import Counter

    now_local = timezone.localtime(timezone.now())
    start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    todays_connections = list(Connection.objects.filter(
        created_at__gte=start_of_day, created_at__lt=end_of_day
    ))

    # --- students connected today: distinct users touched by a new Connection ---
    connected_user_ids = set()
    for c in todays_connections:
        connected_user_ids.add(c.user_a_id)
        connected_user_ids.add(c.user_b_id)
    students_connected_today = len(connected_user_ids)

    # --- average match time: accepted requests resolved today ---
    resolved_today = MatchRequest.objects.filter(
        status="accepted", resolved_at__gte=start_of_day, resolved_at__lt=end_of_day
    )
    avg_seconds = None
    if resolved_today.exists():
        deltas = [(mr.resolved_at - mr.created_at).total_seconds() for mr in resolved_today]
        avg_seconds = sum(deltas) / len(deltas)

    # --- top interest today: most common interest shared by both people
    #     across today's new connections ---
    interest_counter = Counter()
    for c in todays_connections:
        a_interests = set(
            UserInterest.objects.filter(user_id=c.user_a_id).values_list("interest__name", flat=True)
        )
        b_interests = set(
            UserInterest.objects.filter(user_id=c.user_b_id).values_list("interest__name", flat=True)
        )
        interest_counter.update(a_interests & b_interests)
    top_interest = interest_counter.most_common(1)
    top_interest_name = top_interest[0][0] if top_interest else None
    top_interest_emoji = INTEREST_EMOJI.get(top_interest_name, "") if top_interest_name else ""

    return {
        "stat_connected_today": students_connected_today,
        "stat_avg_match_seconds": round(avg_seconds) if avg_seconds is not None else None,
        "stat_top_interest": top_interest_name,
        "stat_top_interest_emoji": top_interest_emoji,
    }


@login_required
@ensure_csrf_cookie
def connect_view(request):
    context = {
        "active_page": "connect",
        "incoming_count": MatchRequest.objects.filter(
            recipient=request.user, status="pending"
        ).count(),
        **_get_todays_stats(),
    }
    return render(request, "matching/connect.html", context)


# =====================================================================
# STEP 2 — SEND (replaces the animated "Find a Friend" button)
# =====================================================================
@login_required
@require_POST
def find_friend_view(request):
    match, score = get_best_match(request.user)

    if match is None:
        return JsonResponse({"found": False})

    match_request = MatchRequest.objects.create(
        requester=request.user,
        recipient=match,
        status="pending",
        compatibility_score=score,
    )

    Notification.objects.create(
        user=match,
        type="match",
        title="New match request",
        description=f"{request.user.profile.display_name} wants to connect with you.",
        cta_label="View request",
        cta_href="/connect/?highlight=incoming",
    )

    return JsonResponse({
        "found": True,
        "request_id": match_request.id,
        "created_at": match_request.created_at.isoformat(),
    })


# =====================================================================
# STEP 2 — POLL STATUS (powers the "waiting" screen for real)
# =====================================================================
@login_required
def match_status_view(request, request_id):
    match_request = get_object_or_404(
        MatchRequest, id=request_id, requester=request.user
    )

    data = {
        "status": match_request.status,
        "created_at": match_request.created_at.isoformat(),
    }

    if match_request.status == "accepted":
        other = match_request.recipient
        connection = Connection.objects.filter(match_request=match_request).first()
        data.update({
            "other_user_id": other.id,
            "other_name": other.profile.display_name,
            "other_country": other.profile.country,
            "compatibility_score": match_request.compatibility_score,
            "conversation_id": connection.conversation.id if connection and hasattr(connection, "conversation") else None,
        })

    return JsonResponse(data)


# =====================================================================
# STEP 2 — CANCEL (requester backs out while still pending)
# =====================================================================
@login_required
@require_POST
def cancel_match_request_view(request, request_id):
    match_request = get_object_or_404(
        MatchRequest, id=request_id, requester=request.user, status="pending"
    )
    match_request.status = "cancelled"
    match_request.resolved_at = timezone.now()
    match_request.save()
    return JsonResponse({"ok": True})


# =====================================================================
# STEP 2 — INCOMING REQUESTS (for the recipient's badge + modal)
# =====================================================================
@login_required
def incoming_requests_view(request):
    pending = MatchRequest.objects.filter(
        recipient=request.user, status="pending"
    ).select_related("requester__profile").order_by("-created_at")

    results = []
    for mr in pending:
        p = mr.requester.profile
        results.append({
            "request_id": mr.id,
            "name": p.display_name,
            "country": p.country,
            "languages": ", ".join(filter(None, [p.primary_language, p.secondary_language])),
            "compatibility_score": mr.compatibility_score,
        })

    return JsonResponse({"requests": results})


# =====================================================================
# STEP 2 — ACCEPT
# =====================================================================
@login_required
@require_POST
def accept_match_view(request, request_id):
    match_request = get_object_or_404(
        MatchRequest, id=request_id, recipient=request.user, status="pending"
    )

    match_request.status = "accepted"
    match_request.resolved_at = timezone.now()
    match_request.save()

    connection = Connection.objects.create(
        match_request=match_request,
        user_a=match_request.requester,
        user_b=match_request.recipient,
        status="active",
    )
    conversation = Conversation.objects.create(type="direct", connection=connection)

    # --- engagement bookkeeping for both people ---
    from django.db.models import Q as _Q

    for user in (match_request.requester, match_request.recipient):
        eng = _get_or_create_engagement(user)
        eng.conversation_count += 1

        # Recompute distinct countries across ALL of this user's active
        # connections (simpler and less error-prone than trying to
        # incrementally diff "is this a new country or not").
        partner_ids = set()
        for c in Connection.objects.filter(_Q(user_a=user) | _Q(user_b=user), status="active"):
            partner_ids.add(c.user_b_id if c.user_a_id == user.id else c.user_a_id)
        countries = {
            partner.profile.country
            for partner in type(user).objects.filter(id__in=partner_ids).select_related("profile")
            if partner.profile.country
        }
        eng.countries_connected = len(countries)
        eng.save()

        check_and_award_badges(user)
        record_mission_progress(user, 'start_conversation')

    Notification.objects.create(
        user=match_request.requester,
        type="match",
        title="Your match request was accepted!",
        description=f"{match_request.recipient.profile.display_name} accepted — say hi!",
        cta_label="Open chat",
        cta_href=f"/chat/{conversation.id}/",
    )

    return JsonResponse({"ok": True})


# =====================================================================
# STEP 2 — DECLINE
# =====================================================================
@login_required
@require_POST
def decline_match_view(request, request_id):
    match_request = get_object_or_404(
        MatchRequest, id=request_id, recipient=request.user, status="pending"
    )
    match_request.status = "declined"
    match_request.resolved_at = timezone.now()
    match_request.save()
    return JsonResponse({"ok": True})


# =====================================================================
# STEP 3 — JOIN GROUP
# A group only becomes "real" once it has at least 2 people. The first
# person to click Join Group is parked in a solo StudentGroup/GroupMember
# row with no Conversation yet — a waiting room, same idea as a pending
# MatchRequest for 1:1 matching. The next person to click Join Group gets
# slotted into that same group (get_open_group_for prioritizes fuller
# groups first), and THAT is the moment the group becomes real: a
# Conversation gets created and everyone already in it gets credited.
# =====================================================================
def _active_group_members(group):
    """
    The one place this filter is defined. Every function below that
    counts or lists a group's members should call this instead of
    writing GroupMember.objects.filter(...) directly — that's exactly
    how this bug happened: get_open_group_for() in utils.py had the
    user__is_deleted=False filter, but views.py had five separate copies
    of a near-identical query that didn't, so a deleted member's stale
    GroupMember row (left_at still null, since accounts hasn't called
    cleanup_matching_state_for_deleted_user yet) kept getting counted
    and displayed here even though matching had already learned to
    ignore them everywhere else.
    """
    return GroupMember.objects.filter(group=group, left_at__isnull=True, user__is_deleted=False)


def _serialize_group_members(group):
    members = _active_group_members(group).select_related("user__profile")
    return [{"name": m.user.profile.display_name, "country": m.user.profile.country} for m in members]


def _credit_group_membership(user):
    eng = _get_or_create_engagement(user)
    eng.groups_joined += 1
    eng.save()
    check_and_award_badges(user)
    record_mission_progress(user, 'join_a_group')


# Deterministic group naming — NOT one of the 4 real-LLM agents scoped in
# the SRS (Verification/Matching/Translation/Safety). This is plain
# Python: count each member's interests, name the group after whichever
# come up most, no network call, no cost, fits the "simple logic first"
# phasing. Called once, at the moment a group actually forms — the name
# stays stable after that even as more people join, rather than
# reshuffling under existing members.
GROUP_NAME_SUFFIXES = ["Crew", "Circle", "Collective", "Squad", "Hub", "Corner"]


def generate_group_name(group):
    member_user_ids = list(_active_group_members(group).values_list("user_id", flat=True))
    if not member_user_ids:
        return "New Discussion Group"

    # Count interests across ALL members combined, not just an
    # intersection — with 3+ people, everyone can be pairwise compatible
    # without a single interest common to literally everyone, so "most
    # shared overall" is the more robust signal than "shared by all".
    interest_counts = Counter(
        UserInterest.objects.filter(user_id__in=member_user_ids).values_list("interest__name", flat=True)
    )
    if not interest_counts:
        return "New Discussion Group"

    top_interests = [name for name, _ in interest_counts.most_common(2)]
    # group.id makes the suffix vary between groups without needing true
    # randomness — same group always gets the same suffix if regenerated.
    suffix = GROUP_NAME_SUFFIXES[group.id % len(GROUP_NAME_SUFFIXES)]

    if len(top_interests) == 1:
        return f"The {top_interests[0]} {suffix}"
    return f"The {top_interests[0]} & {top_interests[1]} {suffix}"


@login_required
@require_POST
def join_group_view(request):
    user = request.user

    group = get_open_group_for(user, GROUP_MAX_MEMBERS)
    created_new_group = False
    if group is None:
        group = StudentGroup.objects.create(name="New Discussion Group")
        created_new_group = True

    membership = GroupMember.objects.create(group=group, user=user)
    member_count = _active_group_members(group).count()

    if member_count < 2:
        # Still just this one person — not a real group yet. No
        # Conversation, no engagement credit, no notification (nobody
        # else exists to notify yet). Frontend shows a waiting screen
        # and polls group_status_view until someone else joins.
        return JsonResponse({
            "ok": True,
            "formed": False,
            "group_id": group.id,
            "joined_at": membership.joined_at.isoformat(),
        })

    conversation, _ = Conversation.objects.get_or_create(group=group, defaults={"type": "group"})
    other_members = _active_group_members(group).exclude(user=user)

    if member_count == 2:
        # This is the moment the group becomes real — replace the
        # "New Discussion Group" placeholder with a real name based on
        # what the members actually have in common.
        group.name = generate_group_name(group)
        group.save()

        # Credit EVERYONE in it, including whoever was waiting alone
        # before this call, and notify them the same way a match
        # recipient gets notified.
        for gm in _active_group_members(group):
            _credit_group_membership(gm.user)
        for gm in other_members:
            Notification.objects.create(
                user=gm.user,
                type="group",
                title="Your group is ready!",
                description=f"{user.profile.display_name} joined — your group chat is now open.",
                cta_label="Open group chat",
                cta_href=f"/chat/{conversation.id}/",
            )
        # The joiner sees this instantly client-side too, but they still
        # get a Notification for consistency (and so it shows up in their
        # notification history even if they navigate away before seeing
        # the reveal screen).
        Notification.objects.create(
            user=user,
            type="group",
            title="We found a group for you!",
            description="Your group chat is now open — say hi!",
            cta_label="Open group chat",
            cta_href=f"/chat/{conversation.id}/",
        )
    else:
        # Group was already real; only the new joiner gets engagement
        # credit, but existing members still deserve a heads-up.
        _credit_group_membership(user)
        for gm in other_members:
            Notification.objects.create(
                user=gm.user,
                type="group",
                title="Someone joined your group",
                description=f"{user.profile.display_name} joined your group.",
                cta_label="Open group chat",
                cta_href=f"/chat/{conversation.id}/",
            )
        Notification.objects.create(
            user=user,
            type="group",
            title="You joined a group!",
            description=f"Welcome to {group.name} — say hi!",
            cta_label="Open group chat",
            cta_href=f"/chat/{conversation.id}/",
        )

    return JsonResponse({
        "ok": True,
        "formed": True,
        "group_id": group.id,
        "group_name": group.name,
        "conversation_id": conversation.id,
        "members": _serialize_group_members(group),
        "created_new_group": created_new_group,
    })


@login_required
def group_status_view(request, group_id):
    """Polling endpoint for someone waiting alone in a not-yet-formed group."""
    group = get_object_or_404(StudentGroup, id=group_id)
    membership = GroupMember.objects.filter(group=group, user=request.user, left_at__isnull=True).first()
    if membership is None:
        return JsonResponse({"error": "not a member of this group"}, status=403)

    member_count = _active_group_members(group).count()
    if member_count < 2:
        return JsonResponse({"formed": False, "joined_at": membership.joined_at.isoformat()})

    conversation, _ = Conversation.objects.get_or_create(group=group, defaults={"type": "group"})
    return JsonResponse({
        "formed": True,
        "group_id": group.id,
        "group_name": group.name,
        "conversation_id": conversation.id,
        "members": _serialize_group_members(group),
    })


@login_required
@require_POST
def cancel_group_wait_view(request, group_id):
    """
    Back out of a group while still waiting alone. Once the group has
    actually formed (2+ people), this isn't the right action anymore —
    that's a real "Leave Group" (built alongside the chat app), not a
    cancelled wait.
    """
    group = get_object_or_404(StudentGroup, id=group_id)
    member_count = _active_group_members(group).count()
    if member_count >= 2:
        return JsonResponse({"ok": False, "error": "Group already formed — use Leave Group instead."}, status=400)

    gm = get_object_or_404(GroupMember, group_id=group_id, user=request.user, left_at__isnull=True)
    gm.left_at = timezone.now()
    gm.save()
    return JsonResponse({"ok": True})


# =====================================================================
# STATE RECOVERY ON PAGE LOAD
# Fixes the bug where navigating away and back lost track of an
# outstanding friend request or an unformed group — the frontend used to
# only track these in a JS variable, which resets on every page load.
# The requests/groups themselves are real DB rows regardless of what the
# JS remembers, so this just asks the server what's actually pending.
# =====================================================================
@login_required
def my_pending_state_view(request):
    user = request.user

    pending_mr = MatchRequest.objects.filter(requester=user, status="pending").order_by("-created_at").first()

    waiting_group_id = None
    waiting_group_joined_at = None
    for gm in GroupMember.objects.filter(user=user, left_at__isnull=True).select_related("group"):
        count = _active_group_members(gm.group).count()
        if count < 2:
            waiting_group_id = gm.group_id
            waiting_group_joined_at = gm.joined_at.isoformat()
            break

    return JsonResponse({
        "friend_request_id": pending_mr.id if pending_mr else None,
        "friend_request_created_at": pending_mr.created_at.isoformat() if pending_mr else None,
        "waiting_group_id": waiting_group_id,
        "waiting_group_joined_at": waiting_group_joined_at,
    })


# =====================================================================
# STEP 4 — BLOCK (the cascade — must do 3 things, not just create a row)
# =====================================================================
@login_required
@require_POST
def block_user_view(request, user_id):
    from accounts.models import User

    other_user = get_object_or_404(User, id=user_id)

    if other_user.id == request.user.id:
        return JsonResponse({"ok": False, "error": "Cannot block yourself."}, status=400)

    # 1. Create the Block row
    Block.objects.get_or_create(blocker=request.user, blocked=other_user)

    # 2. End any active Connection between the two of them
    from django.db.models import Q as _Q
    connection = Connection.objects.filter(
        _Q(user_a=request.user, user_b=other_user) | _Q(user_a=other_user, user_b=request.user),
        status="active",
    ).first()
    if connection:
        connection.status = "ended"
        connection.ended_reason = "block"
        connection.ended_at = timezone.now()
        connection.save()

    # 3. Nothing else here — feed/comment/matching-pool visibility is
    #    all handled at query time via is_blocked_either_way(), not by
    #    touching any other data. See matching/utils.py.

    return JsonResponse({"ok": True})
