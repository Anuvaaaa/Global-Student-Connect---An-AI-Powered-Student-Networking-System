"""
matching/utils.py

Shared helper functions used by matching/views.py AND by other apps
(social, chat) that need to check blocking or read a user's engagement
stats. Keep this file dependency-light — it's imported across apps.
"""

from django.db.models import Q
from django.utils import timezone

from .models import Block, MatchRequest, Connection
from social.models import UserInterest


# =====================================================================
# STEP 1 — BLOCKING HELPER
# Build this first. Person B's social/views.py imports this to filter
# posts/comments. Tell them as soon as it exists.
# =====================================================================
def is_blocked_either_way(user_a, user_b):
    """
    True if either user has blocked the other, in either direction.
    Block is directional in the DB (blocker -> blocked), but its
    real-world effect must be symmetric — if A blocks B, B shouldn't
    see A's stuff either, even though B never did anything.
    """
    return Block.objects.filter(
        Q(blocker=user_a, blocked=user_b) | Q(blocker=user_b, blocked=user_a)
    ).exists()


# =====================================================================
# STEP 2 — COMPATIBILITY SCORE
# Deliberately NOT an AI call yet (per the deferred-AI-agents decision
# in the project brief). Plain Python: count shared interests, small
# bonus for same country. Swap this out for a real "Matching Agent"
# call later without changing anything that calls it.
# =====================================================================
def compute_compatibility_score(user_a, user_b):
    a_interests = set(
        UserInterest.objects.filter(user=user_a).values_list("interest_id", flat=True)
    )
    b_interests = set(
        UserInterest.objects.filter(user=user_b).values_list("interest_id", flat=True)
    )
    shared_count = len(a_interests & b_interests)

    score = 60 + shared_count * 8  # base + points per shared interest

    profile_a = getattr(user_a, "profile", None)
    profile_b = getattr(user_b, "profile", None)
    if profile_a and profile_b and profile_a.country and profile_a.country == profile_b.country:
        score += 5

    return min(score, 98)  # cap it — 100% feels fake, prototype capped at 98 too


# =====================================================================
# CANDIDATE POOL
# Used by connect_view to decide who's even eligible to be matched.
# Excludes: self, blocked people (either direction), people already in
# an active Connection with this user, people from ANY past connection
# with this user (active or ended — once you've ended a chat with
# someone, you should never be re-matched with them, per team decision),
# and people with an unresolved (pending) MatchRequest between the two.
# Filtered to same gender per Profile.gender, per the breakdown doc.
# =====================================================================
def get_available_matches(user):
    from accounts.models import User  # local import avoids a circular import at module load

    profile = getattr(user, "profile", None)
    if profile is None:
        return User.objects.none()

    all_connection_pairs = set(
        Connection.objects.filter(Q(user_a=user) | Q(user_b=user))
        .values_list("user_a_id", "user_b_id")
    )
    connected_user_ids = set()
    for a_id, b_id in all_connection_pairs:
        connected_user_ids.add(a_id)
        connected_user_ids.add(b_id)
    connected_user_ids.discard(user.id)

    pending_ids = set(
        MatchRequest.objects.filter(
            Q(requester=user) | Q(recipient=user), status="pending"
        ).values_list("requester_id", "recipient_id")
    )
    pending_user_ids = set()
    for req_id, rec_id in pending_ids:
        pending_user_ids.add(req_id)
        pending_user_ids.add(rec_id)
    pending_user_ids.discard(user.id)

    blocked_ids = set(
        Block.objects.filter(blocker=user).values_list("blocked_id", flat=True)
    ) | set(
        Block.objects.filter(blocked=user).values_list("blocker_id", flat=True)
    )

    exclude_ids = {user.id} | connected_user_ids | pending_user_ids | blocked_ids

    candidates = User.objects.filter(
        profile__gender=profile.gender,
        profile__profile_setup_complete=True,
        is_deleted=False,
    ).exclude(id__in=exclude_ids)

    return candidates


def get_open_group_for(user, group_max_members, min_overlap_ratio=0.4):
    """
    Finds a StudentGroup with room for this user AND that they're actually
    compatible with — same gender as every current member (matching the
    rule used for 1:1 matching), AND at least min_overlap_ratio of shared
    interests with EVERY current member, not just some of them.

    Prioritizes groups that are MORE full first (not emptier ones) among
    the compatible candidates.
    """
    from .models import GroupMember, StudentGroup

    already_in_ids = set(
        GroupMember.objects.filter(user=user).values_list("group_id", flat=True)
    )

    user_profile = getattr(user, "profile", None)
    user_interest_ids = set(
        UserInterest.objects.filter(user=user).values_list("interest_id", flat=True)
    )

    candidates = []
    for group in StudentGroup.objects.exclude(id__in=already_in_ids):
        members = list(
            GroupMember.objects.filter(
                group=group, left_at__isnull=True, user__is_deleted=False
            ).select_related("user__profile")
        )
        member_count = len(members)
        if member_count == 0 or member_count >= group_max_members:
            continue

        compatible_with_everyone = True
        for gm in members:
            member_profile = getattr(gm.user, "profile", None)

            if not user_profile or not member_profile or user_profile.gender != member_profile.gender:
                compatible_with_everyone = False
                break

            member_interest_ids = set(
                UserInterest.objects.filter(user=gm.user).values_list("interest_id", flat=True)
            )
            if not user_interest_ids or not member_interest_ids:
                compatible_with_everyone = False
                break
            overlap_ratio = len(user_interest_ids & member_interest_ids) / min(
                len(user_interest_ids), len(member_interest_ids)
            )
            if overlap_ratio < min_overlap_ratio:
                compatible_with_everyone = False
                break

        if compatible_with_everyone:
            candidates.append((member_count, group))

    if not candidates:
        return None

    candidates.sort(key=lambda pair: -pair[0])  # most-filled compatible group first
    return candidates[0][1]


def get_best_match(user):
    """
    Picks the single best candidate for 'Find a Friend' — highest
    compatibility score. Returns (user, score) or (None, None) if the
    pool is empty.
    """
    candidates = list(get_available_matches(user))
    if not candidates:
        return None, None

    scored = [(c, compute_compatibility_score(user, c)) for c in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[0]


# =====================================================================
# ACCOUNT DELETION — GROUP SLOT RELEASE
#
# Call this from accounts' delete-account view, immediately after
# setting is_deleted=True on the User.
#
# Why this exists (and Connection doesn't need an equivalent): groups
# have real capacity limits — get_open_group_for() checks
# member_count >= group_max_members using left_at__isnull=True to
# decide if a group has room, and gatekeeps new joiners against every
# "active" member's profile/interests. A deleted user whose GroupMember
# row stays active forever permanently occupies a real slot and keeps
# influencing who's allowed to join — a functional problem for OTHER,
# currently-active students, not just a display issue. 1:1 Connections
# have no such capacity concept, so they're deliberately left untouched.
#
# Does NOT delete the GroupMember row (soft-delete pattern, same as
# everything else in this project) — just marks it left, same as if
# the user had used Leave Group themselves.
# =====================================================================
def release_group_slots_for_deleted_user(user):
    from .models import GroupMember
    GroupMember.objects.filter(user=user, left_at__isnull=True).update(left_at=timezone.now())


# =====================================================================
# ACCOUNT DELETION — PENDING MATCH REQUEST CLEANUP
#
# Same shape of problem as the group-slot release above, applied to
# MatchRequest instead of GroupMember. A pending MatchRequest is a LIVE,
# actionable state — unlike an already-resolved Connection (which has no
# capacity concept and is fine to just anonymize on display), a pending
# request sitting in someone else's inbox can still be clicked Accept on
# at any time. If the requester or recipient has since deleted their
# account, accepting it would create a real Connection + Conversation
# with a nonexistent account, and fire a Notification at a deleted user
# — not a display nicety, a live bug path for a currently-active person.
#
# Sets status='cancelled', matching the same status a normal "Cancel
# Request" click produces — no new status value needed.
# =====================================================================
def cancel_pending_matches_for_deleted_user(user):
    MatchRequest.objects.filter(
        Q(requester=user) | Q(recipient=user), status="pending"
    ).update(status="cancelled", resolved_at=timezone.now())


# =====================================================================
# SINGLE ENTRY POINT FOR accounts' DELETE-ACCOUNT VIEW
# One import, one function call, right after is_deleted=True gets set:
#
#   from matching.utils import cleanup_matching_state_for_deleted_user
#   cleanup_matching_state_for_deleted_user(user)
#
# Covers both the group-slot and pending-match-request problems above in
# one call, so accounts doesn't need to know these are two separate
# fixes under the hood.
# =====================================================================
def cleanup_matching_state_for_deleted_user(user):
    release_group_slots_for_deleted_user(user)
    cancel_pending_matches_for_deleted_user(user)
