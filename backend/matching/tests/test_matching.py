# TARGET PATH: matching/tests.py
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, University
from social.models import Interest, UserInterest
from chat.models import Conversation

from ..models import Block, Connection, GroupMember, MatchRequest, StudentGroup
from ..utils import (
    cancel_pending_matches_for_deleted_user,
    cleanup_matching_state_for_deleted_user,
    compute_compatibility_score,
    get_available_matches,
    get_best_match,
    get_open_group_for,
    is_blocked_either_way,
    release_group_slots_for_deleted_user,
)

User = get_user_model()


def _make_user(email, gender="Male", country="Bangladesh", complete_profile=True, is_deleted=False):
    university, _ = University.objects.get_or_create(
        domain="example.edu", defaults={"name": "Example University"},
    )
    user = User.objects.create_user(
        username=email, email=email, google_id=f"gid-{email}",
        university=university, is_verified=True, password="testpass123",
        is_deleted=is_deleted,
    )
    if complete_profile:
        Profile.objects.create(
            user=user, display_name=email.split("@")[0], country=country,
            gender=gender, primary_language="English", secondary_language="",
            profile_setup_complete=True,
        )
    return user


def _add_interests(user, names):
    for name in names:
        interest, _ = Interest.objects.get_or_create(name=name)
        UserInterest.objects.create(user=user, interest=interest)


# =====================================================================
# MODELS
# =====================================================================
class BlockModelTests(TestCase):
    def setUp(self):
        self.user_a = _make_user("a@example.edu")
        self.user_b = _make_user("b@example.edu")

    # --- normal input ---
    def test_block_created_successfully(self):
        Block.objects.create(blocker=self.user_a, blocked=self.user_b)

        self.assertEqual(Block.objects.count(), 1)

    # --- boundary: unique constraint on (blocker, blocked) ---
    def test_duplicate_block_same_direction_raises_integrity_error(self):
        Block.objects.create(blocker=self.user_a, blocked=self.user_b)

        with self.assertRaises(IntegrityError):
            Block.objects.create(blocker=self.user_a, blocked=self.user_b)

    # --- behavior: reverse direction is a distinct, independent row ---
    def test_reverse_direction_block_is_a_separate_allowed_row(self):
        Block.objects.create(blocker=self.user_a, blocked=self.user_b)
        Block.objects.create(blocker=self.user_b, blocked=self.user_a)

        self.assertEqual(Block.objects.count(), 2)


# =====================================================================
# UTILS — is_blocked_either_way
# =====================================================================
class IsBlockedEitherWayTests(TestCase):
    def setUp(self):
        self.user_a = _make_user("a@example.edu")
        self.user_b = _make_user("b@example.edu")
        self.user_c = _make_user("c@example.edu")

    # --- normal input ---
    def test_no_block_returns_false(self):
        self.assertFalse(is_blocked_either_way(self.user_a, self.user_b))

    def test_direct_direction_returns_true(self):
        Block.objects.create(blocker=self.user_a, blocked=self.user_b)

        self.assertTrue(is_blocked_either_way(self.user_a, self.user_b))

    # --- behavior: symmetric enforcement, the whole point of this helper ---
    def test_reverse_argument_order_still_returns_true(self):
        Block.objects.create(blocker=self.user_a, blocked=self.user_b)

        self.assertTrue(is_blocked_either_way(self.user_b, self.user_a))

    # --- unexpected input: unrelated third party ---
    def test_unrelated_pair_returns_false(self):
        Block.objects.create(blocker=self.user_a, blocked=self.user_b)

        self.assertFalse(is_blocked_either_way(self.user_a, self.user_c))


# =====================================================================
# UTILS — compute_compatibility_score
# =====================================================================
class ComputeCompatibilityScoreTests(TestCase):
    def setUp(self):
        self.user_a = _make_user("a@example.edu", country="Bangladesh")
        self.user_b = _make_user("b@example.edu", country="Bangladesh")

    # --- normal input ---
    def test_base_score_with_no_shared_interests(self):
        score = compute_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, 65)  # 60 base + 5 same-country bonus, 0 shared

    def test_score_increases_with_each_shared_interest(self):
        _add_interests(self.user_a, ["Music", "Travel"])
        _add_interests(self.user_b, ["Music", "Travel"])

        score = compute_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, 81)  # 60 + 2*8 + 5

    # --- category: same country vs different country ---
    def test_no_bonus_when_countries_differ(self):
        other_country_user = _make_user("d@example.edu", country="Kenya")

        score = compute_compatibility_score(self.user_a, other_country_user)

        self.assertEqual(score, 60)

    # --- boundary: score capped at 98 even with many shared interests ---
    def test_score_capped_at_ninety_eight(self):
        many_interests = ["Music", "Travel", "Reading", "Photography", "Art & Design", "Cricket"]
        _add_interests(self.user_a, many_interests)
        _add_interests(self.user_b, many_interests)

        score = compute_compatibility_score(self.user_a, self.user_b)

        self.assertEqual(score, 98)

    # --- unexpected input: a user with no Profile at all ---
    def test_no_country_bonus_when_profile_missing(self):
        no_profile_user = _make_user("e@example.edu", complete_profile=False)

        score = compute_compatibility_score(self.user_a, no_profile_user)

        self.assertEqual(score, 60)  # does not raise, just skips the bonus


# =====================================================================
# UTILS — get_available_matches
# =====================================================================
class GetAvailableMatchesTests(TestCase):
    def setUp(self):
        self.requester = _make_user("requester@example.edu", gender="Male")

    # --- normal input ---
    def test_returns_eligible_same_gender_candidate(self):
        candidate = _make_user("candidate@example.edu", gender="Male")

        results = get_available_matches(self.requester)

        self.assertIn(candidate, results)

    # --- boundary: empty pool ---
    def test_empty_pool_when_no_other_users_exist(self):
        results = get_available_matches(self.requester)

        self.assertEqual(list(results), [])

    # --- category: excludes different gender ---
    def test_excludes_different_gender(self):
        _make_user("other-gender@example.edu", gender="Female")

        results = get_available_matches(self.requester)

        self.assertEqual(list(results), [])

    # --- category: excludes incomplete profile setup ---
    def test_excludes_incomplete_profile(self):
        incomplete = _make_user("incomplete@example.edu", gender="Male")
        incomplete.profile.profile_setup_complete = False
        incomplete.profile.save()

        results = get_available_matches(self.requester)

        self.assertNotIn(incomplete, results)

    # --- category: excludes soft-deleted users ---
    def test_excludes_deleted_user(self):
        deleted = _make_user("deleted@example.edu", gender="Male", is_deleted=True)

        results = get_available_matches(self.requester)

        self.assertNotIn(deleted, results)

    # --- behavior: excludes self ---
    def test_excludes_self(self):
        results = get_available_matches(self.requester)

        self.assertNotIn(self.requester, results)

    # --- behavior: excludes blocked user, requester as blocker ---
    def test_excludes_user_blocked_by_requester(self):
        blocked = _make_user("blocked@example.edu", gender="Male")
        Block.objects.create(blocker=self.requester, blocked=blocked)

        results = get_available_matches(self.requester)

        self.assertNotIn(blocked, results)

    # --- behavior: excludes blocked user, requester as the blocked party ---
    def test_excludes_user_who_blocked_requester(self):
        blocker = _make_user("blocker@example.edu", gender="Male")
        Block.objects.create(blocker=blocker, blocked=self.requester)

        results = get_available_matches(self.requester)

        self.assertNotIn(blocker, results)

    # --- behavior: excludes users already in an active connection ---
    def test_excludes_actively_connected_user(self):
        partner = _make_user("partner@example.edu", gender="Male")
        mr = MatchRequest.objects.create(requester=self.requester, recipient=partner, status="accepted")
        Connection.objects.create(match_request=mr, user_a=self.requester, user_b=partner, status="active")

        results = get_available_matches(self.requester)

        self.assertNotIn(partner, results)

    # --- behavior: excludes users from an ENDED connection too (never re-match) ---
    def test_excludes_previously_ended_connection_user(self):
        ex_partner = _make_user("ex@example.edu", gender="Male")
        mr = MatchRequest.objects.create(requester=self.requester, recipient=ex_partner, status="accepted")
        Connection.objects.create(
            match_request=mr, user_a=self.requester, user_b=ex_partner,
            status="ended", ended_reason="manual_end",
        )

        results = get_available_matches(self.requester)

        self.assertNotIn(ex_partner, results)

    # --- behavior: excludes users with a pending request, requester as sender ---
    def test_excludes_user_with_pending_request_sent_by_requester(self):
        pending_target = _make_user("pending-target@example.edu", gender="Male")
        MatchRequest.objects.create(requester=self.requester, recipient=pending_target, status="pending")

        results = get_available_matches(self.requester)

        self.assertNotIn(pending_target, results)

    # --- behavior: excludes users with a pending request, requester as recipient ---
    def test_excludes_user_with_pending_request_received_by_requester(self):
        pending_sender = _make_user("pending-sender@example.edu", gender="Male")
        MatchRequest.objects.create(requester=pending_sender, recipient=self.requester, status="pending")

        results = get_available_matches(self.requester)

        self.assertNotIn(pending_sender, results)

    # --- unexpected input: requester has no Profile at all ---
    def test_requester_with_no_profile_returns_empty_queryset(self):
        bare_user = _make_user("bare@example.edu", complete_profile=False)

        results = get_available_matches(bare_user)

        self.assertEqual(list(results), [])


# =====================================================================
# UTILS — get_open_group_for
# =====================================================================
class GetOpenGroupForTests(TestCase):
    def setUp(self):
        self.user = _make_user("joiner@example.edu", gender="Male")
        _add_interests(self.user, ["Music", "Travel"])

    def _make_group_with_member(self, gender="Male", interests=("Music", "Travel"), name="Group"):
        group = StudentGroup.objects.create(name=name)
        member = _make_user(f"{name.lower()}-member@example.edu", gender=gender)
        _add_interests(member, list(interests))
        GroupMember.objects.create(group=group, user=member)
        return group

    # --- normal input ---
    def test_finds_compatible_group_with_room(self):
        group = self._make_group_with_member()

        result = get_open_group_for(self.user, group_max_members=4)

        self.assertEqual(result, group)

    # --- boundary: group already at exactly max members ---
    def test_group_at_exactly_max_members_is_excluded(self):
        group = StudentGroup.objects.create(name="Full")
        for i in range(4):
            member = _make_user(f"full-member-{i}@example.edu", gender="Male")
            _add_interests(member, ["Music"])
            GroupMember.objects.create(group=group, user=member)

        result = get_open_group_for(self.user, group_max_members=4)

        self.assertIsNone(result)

    # --- boundary: group with zero active members is excluded ---
    def test_group_with_zero_active_members_is_excluded(self):
        StudentGroup.objects.create(name="Empty")

        result = get_open_group_for(self.user, group_max_members=4)

        self.assertIsNone(result)

    # --- boundary: no groups exist at all ---
    def test_no_groups_exist_returns_none(self):
        result = get_open_group_for(self.user, group_max_members=4)

        self.assertIsNone(result)

    # --- category: gender mismatch excludes the group ---
    def test_gender_mismatch_excludes_group(self):
        self._make_group_with_member(gender="Female")

        result = get_open_group_for(self.user, group_max_members=4)

        self.assertIsNone(result)

    # --- category: overlap ratio below minimum excludes the group ---
    def test_overlap_below_minimum_ratio_excludes_group(self):
        self._make_group_with_member(interests=("Cricket", "Football", "Badminton"))

        result = get_open_group_for(self.user, group_max_members=4, min_overlap_ratio=0.4)

        self.assertIsNone(result)

    # --- boundary: overlap ratio exactly at the minimum is included ---
    def test_overlap_exactly_at_minimum_ratio_is_included(self):
        # user has 2 interests (Music, Travel); member shares exactly 1 of
        # them plus one unrelated one -> overlap ratio = 1/2 = 0.5, which
        # is the smaller side's count, satisfying a 0.4 minimum exactly.
        group = self._make_group_with_member(interests=("Music", "Cricket"))

        result = get_open_group_for(self.user, group_max_members=4, min_overlap_ratio=0.4)

        self.assertEqual(result, group)

    # --- unexpected input: user has no interests at all ---
    def test_user_with_no_interests_finds_no_compatible_group(self):
        bare_user = _make_user("bare-joiner@example.edu", gender="Male")
        self._make_group_with_member()

        result = get_open_group_for(bare_user, group_max_members=4)

        self.assertIsNone(result)

    # --- behavior: excludes groups the user already belongs to ---
    def test_excludes_group_user_already_belongs_to(self):
        group = self._make_group_with_member()
        GroupMember.objects.create(group=group, user=self.user)

        result = get_open_group_for(self.user, group_max_members=4)

        self.assertIsNone(result)

    # --- behavior: prioritizes the fuller compatible group ---
    def test_prioritizes_more_full_group_among_compatible_options(self):
        emptier_group = self._make_group_with_member(name="Emptier")
        fuller_group = self._make_group_with_member(name="Fuller")
        extra_member = _make_user("fuller-member-2@example.edu", gender="Male")
        _add_interests(extra_member, ["Music", "Travel"])
        GroupMember.objects.create(group=fuller_group, user=extra_member)

        result = get_open_group_for(self.user, group_max_members=4)

        self.assertEqual(result, fuller_group)


# =====================================================================
# UTILS — get_best_match
# =====================================================================
class GetBestMatchTests(TestCase):
    def setUp(self):
        self.user = _make_user("seeker@example.edu", gender="Male")

    # --- boundary: empty candidate pool ---
    def test_empty_pool_returns_none_none(self):
        result = get_best_match(self.user)

        self.assertEqual(result, (None, None))

    # --- behavior: delegates scoring to the fail-open service and picks the highest score ---
    @patch("ai_agents.services.matching_service.get_compatibility_score")
    def test_returns_candidate_with_highest_score(self, mock_score):
        low_candidate = _make_user("low@example.edu", gender="Male")
        high_candidate = _make_user("high@example.edu", gender="Male")

        def _score(user_a, user_b):
            return 95.0 if user_b.id == high_candidate.id else 40.0
        mock_score.side_effect = _score

        best_user, best_score = get_best_match(self.user)

        self.assertEqual(best_user, high_candidate)
        self.assertEqual(best_score, 95.0)


# =====================================================================
# UTILS — account-deletion cleanup
# =====================================================================
class ReleaseGroupSlotsForDeletedUserTests(TestCase):
    # --- normal input ---
    def test_marks_active_membership_as_left(self):
        user = _make_user("leaver@example.edu")
        group = StudentGroup.objects.create(name="G")
        gm = GroupMember.objects.create(group=group, user=user)

        release_group_slots_for_deleted_user(user)

        gm.refresh_from_db()
        self.assertIsNotNone(gm.left_at)

    # --- unexpected input: user has no group membership at all ---
    def test_no_op_when_user_has_no_membership(self):
        user = _make_user("no-groups@example.edu")

        release_group_slots_for_deleted_user(user)  # should not raise

        self.assertEqual(GroupMember.objects.count(), 0)

    # --- boundary: an already-left membership stays untouched ---
    def test_does_not_overwrite_already_left_membership(self):
        user = _make_user("already-left@example.edu")
        group = StudentGroup.objects.create(name="G")
        original_left_at = timezone.now()
        gm = GroupMember.objects.create(group=group, user=user, left_at=original_left_at)

        release_group_slots_for_deleted_user(user)

        gm.refresh_from_db()
        self.assertEqual(gm.left_at, original_left_at)


class CancelPendingMatchesForDeletedUserTests(TestCase):
    # --- normal input ---
    def test_cancels_pending_request_as_requester(self):
        user = _make_user("requester@example.edu")
        recipient = _make_user("recipient@example.edu")
        mr = MatchRequest.objects.create(requester=user, recipient=recipient, status="pending")

        cancel_pending_matches_for_deleted_user(user)

        mr.refresh_from_db()
        self.assertEqual(mr.status, "cancelled")
        self.assertIsNotNone(mr.resolved_at)

    def test_cancels_pending_request_as_recipient(self):
        requester = _make_user("requester2@example.edu")
        user = _make_user("recipient2@example.edu")
        mr = MatchRequest.objects.create(requester=requester, recipient=user, status="pending")

        cancel_pending_matches_for_deleted_user(user)

        mr.refresh_from_db()
        self.assertEqual(mr.status, "cancelled")

    # --- unexpected input: no pending requests exist ---
    def test_no_op_when_no_pending_requests_exist(self):
        user = _make_user("nobody@example.edu")

        cancel_pending_matches_for_deleted_user(user)  # should not raise

    # --- boundary: already-resolved requests are left untouched ---
    def test_does_not_touch_already_accepted_request(self):
        user = _make_user("requester3@example.edu")
        recipient = _make_user("recipient3@example.edu")
        mr = MatchRequest.objects.create(requester=user, recipient=recipient, status="accepted")

        cancel_pending_matches_for_deleted_user(user)

        mr.refresh_from_db()
        self.assertEqual(mr.status, "accepted")


class CleanupMatchingStateForDeletedUserTests(TestCase):
    # --- behavior: single entry point covers both fixes ---
    @patch("matching.utils.release_group_slots_for_deleted_user")
    @patch("matching.utils.cancel_pending_matches_for_deleted_user")
    def test_calls_both_cleanup_functions(self, mock_cancel, mock_release):
        user = _make_user("deleted-account@example.edu")

        cleanup_matching_state_for_deleted_user(user)

        mock_release.assert_called_once_with(user)
        mock_cancel.assert_called_once_with(user)


# =====================================================================
# VIEWS
# =====================================================================
class ConnectViewTests(TestCase):
    def setUp(self):
        self.user = _make_user("viewer@example.edu")
        self.client = Client()
        self.client.force_login(self.user)

    # --- normal input ---
    def test_renders_successfully_for_logged_in_user(self):
        response = self.client.get(reverse("matching:connect"))

        self.assertEqual(response.status_code, 200)

    # --- behavior: login required ---
    def test_requires_login(self):
        anonymous_client = Client()

        response = anonymous_client.get(reverse("matching:connect"))

        self.assertNotEqual(response.status_code, 200)

    # --- boundary: incoming_count reflects zero pending requests ---
    def test_incoming_count_zero_when_no_pending_requests(self):
        response = self.client.get(reverse("matching:connect"))

        self.assertEqual(response.context["incoming_count"], 0)


class FindFriendViewTests(TestCase):
    def setUp(self):
        self.requester = _make_user("requester@example.edu")
        self.client = Client()
        self.client.force_login(self.requester)

    # --- normal input ---
    @patch("ai_agents.services.matching_service.get_compatibility_score", return_value=80.0)
    def test_creates_match_request_and_notification_when_candidate_exists(self, mock_score):
        candidate = _make_user("candidate@example.edu")

        response = self.client.post(reverse("matching:find_friend"))
        data = json.loads(response.content)

        self.assertTrue(data["found"])
        self.assertTrue(MatchRequest.objects.filter(requester=self.requester, recipient=candidate).exists())

    # --- boundary: empty candidate pool ---
    def test_returns_found_false_when_no_candidates(self):
        response = self.client.post(reverse("matching:find_friend"))
        data = json.loads(response.content)

        self.assertFalse(data["found"])
        self.assertEqual(MatchRequest.objects.count(), 0)

    # --- behavior: wrong HTTP method rejected ---
    def test_get_request_not_allowed(self):
        response = self.client.get(reverse("matching:find_friend"))

        self.assertEqual(response.status_code, 405)

    # --- behavior: login required ---
    def test_requires_login(self):
        anonymous_client = Client()

        response = anonymous_client.post(reverse("matching:find_friend"))

        self.assertNotEqual(response.status_code, 200)


class MatchStatusViewTests(TestCase):
    def setUp(self):
        self.requester = _make_user("requester@example.edu")
        self.recipient = _make_user("recipient@example.edu")
        self.client = Client()
        self.client.force_login(self.requester)

    # --- normal input: still pending ---
    def test_pending_request_returns_pending_status(self):
        mr = MatchRequest.objects.create(requester=self.requester, recipient=self.recipient, status="pending")

        response = self.client.get(reverse("matching:match_status", args=[mr.id]))
        data = json.loads(response.content)

        self.assertEqual(data["status"], "pending")

    # --- behavior: accepted request includes connection/conversation details ---
    def test_accepted_request_includes_conversation_id(self):
        mr = MatchRequest.objects.create(
            requester=self.requester, recipient=self.recipient, status="accepted", compatibility_score=75,
        )
        connection = Connection.objects.create(
            match_request=mr, user_a=self.requester, user_b=self.recipient, status="active",
        )
        Conversation.objects.create(type="direct", connection=connection)

        response = self.client.get(reverse("matching:match_status", args=[mr.id]))
        data = json.loads(response.content)

        self.assertIsNotNone(data["conversation_id"])

    # --- unexpected input: nonexistent request id ---
    def test_nonexistent_request_id_returns_404(self):
        response = self.client.get(reverse("matching:match_status", args=[999999]))

        self.assertEqual(response.status_code, 404)

    # --- unexpected input: requesting someone else's match request ---
    def test_cannot_view_another_users_match_request(self):
        other_user = _make_user("other@example.edu")
        mr = MatchRequest.objects.create(requester=other_user, recipient=self.recipient, status="pending")

        response = self.client.get(reverse("matching:match_status", args=[mr.id]))

        self.assertEqual(response.status_code, 404)


class CancelMatchRequestViewTests(TestCase):
    def setUp(self):
        self.requester = _make_user("requester@example.edu")
        self.recipient = _make_user("recipient@example.edu")
        self.client = Client()
        self.client.force_login(self.requester)

    # --- normal input ---
    def test_cancels_pending_request(self):
        mr = MatchRequest.objects.create(requester=self.requester, recipient=self.recipient, status="pending")

        self.client.post(reverse("matching:cancel_request", args=[mr.id]))

        mr.refresh_from_db()
        self.assertEqual(mr.status, "cancelled")

    # --- unexpected input: already-resolved request cannot be cancelled ---
    def test_already_accepted_request_returns_404(self):
        mr = MatchRequest.objects.create(requester=self.requester, recipient=self.recipient, status="accepted")

        response = self.client.post(reverse("matching:cancel_request", args=[mr.id]))

        self.assertEqual(response.status_code, 404)


class IncomingRequestsViewTests(TestCase):
    def setUp(self):
        self.recipient = _make_user("recipient@example.edu")
        self.client = Client()
        self.client.force_login(self.recipient)

    # --- normal input ---
    def test_lists_pending_incoming_requests(self):
        requester = _make_user("requester@example.edu")
        MatchRequest.objects.create(
            requester=requester, recipient=self.recipient, status="pending", compatibility_score=88,
        )

        response = self.client.get(reverse("matching:incoming_requests"))
        data = json.loads(response.content)

        self.assertEqual(len(data["requests"]), 1)
        self.assertEqual(data["requests"][0]["compatibility_score"], 88)

    # --- boundary: empty inbox ---
    def test_empty_list_when_no_incoming_requests(self):
        response = self.client.get(reverse("matching:incoming_requests"))
        data = json.loads(response.content)

        self.assertEqual(data["requests"], [])

    # --- category: excludes non-pending requests ---
    def test_excludes_already_declined_request(self):
        requester = _make_user("requester2@example.edu")
        MatchRequest.objects.create(requester=requester, recipient=self.recipient, status="declined")

        response = self.client.get(reverse("matching:incoming_requests"))
        data = json.loads(response.content)

        self.assertEqual(data["requests"], [])


class AcceptMatchViewTests(TestCase):
    def setUp(self):
        self.requester = _make_user("requester@example.edu")
        self.recipient = _make_user("recipient@example.edu")
        self.client = Client()
        self.client.force_login(self.recipient)
        self.mr = MatchRequest.objects.create(
            requester=self.requester, recipient=self.recipient, status="pending",
        )

    # --- normal input ---
    @patch("matching.views.record_mission_progress")
    @patch("matching.views.check_and_award_badges")
    def test_creates_connection_and_conversation(self, mock_badges, mock_mission):
        self.client.post(reverse("matching:accept_match", args=[self.mr.id]))

        self.mr.refresh_from_db()
        self.assertEqual(self.mr.status, "accepted")
        self.assertTrue(Connection.objects.filter(match_request=self.mr, status="active").exists())
        connection = Connection.objects.get(match_request=self.mr)
        self.assertTrue(Conversation.objects.filter(connection=connection).exists())

    # --- behavior: engagement bookkeeping credited to both users ---
    @patch("matching.views.record_mission_progress")
    @patch("matching.views.check_and_award_badges")
    def test_credits_both_users_engagement(self, mock_badges, mock_mission):
        self.client.post(reverse("matching:accept_match", args=[self.mr.id]))

        self.assertEqual(mock_badges.call_count, 2)
        self.assertEqual(mock_mission.call_count, 2)

    # --- unexpected input: only the recipient may accept ---
    @patch("matching.views.record_mission_progress")
    @patch("matching.views.check_and_award_badges")
    def test_requester_cannot_accept_own_request(self, mock_badges, mock_mission):
        requester_client = Client()
        requester_client.force_login(self.requester)

        response = requester_client.post(reverse("matching:accept_match", args=[self.mr.id]))

        self.assertEqual(response.status_code, 404)

    # --- unexpected input: nonexistent request id ---
    def test_nonexistent_request_returns_404(self):
        response = self.client.post(reverse("matching:accept_match", args=[999999]))

        self.assertEqual(response.status_code, 404)


class DeclineMatchViewTests(TestCase):
    def setUp(self):
        self.requester = _make_user("requester@example.edu")
        self.recipient = _make_user("recipient@example.edu")
        self.client = Client()
        self.client.force_login(self.recipient)

    # --- normal input ---
    def test_declines_pending_request(self):
        mr = MatchRequest.objects.create(requester=self.requester, recipient=self.recipient, status="pending")

        self.client.post(reverse("matching:decline_match", args=[mr.id]))

        mr.refresh_from_db()
        self.assertEqual(mr.status, "declined")
        self.assertFalse(Connection.objects.filter(match_request=mr).exists())


class JoinGroupViewTests(TestCase):
    def setUp(self):
        self.user = _make_user("joiner@example.edu")
        _add_interests(self.user, ["Music", "Travel"])
        self.client = Client()
        self.client.force_login(self.user)

    # --- normal input: first person waits alone, group not yet formed ---
    def test_first_joiner_gets_waiting_state_not_formed(self):
        response = self.client.post(reverse("matching:join_group"))
        data = json.loads(response.content)

        self.assertFalse(data["formed"])
        self.assertEqual(GroupMember.objects.filter(user=self.user).count(), 1)

    # --- behavior: second compatible joiner forms the group ---
    @patch("matching.views.record_mission_progress")
    @patch("matching.views.check_and_award_badges")
    def test_second_joiner_forms_the_group_and_creates_conversation(self, mock_badges, mock_mission):
        self.client.post(reverse("matching:join_group"))
        second_user = _make_user("joiner2@example.edu")
        _add_interests(second_user, ["Music", "Travel"])
        second_client = Client()
        second_client.force_login(second_user)

        response = second_client.post(reverse("matching:join_group"))
        data = json.loads(response.content)

        self.assertTrue(data["formed"])
        self.assertTrue(Conversation.objects.filter(group_id=data["group_id"]).exists())

    # --- behavior: third joiner credited without re-triggering group-formation notifications ---
    @patch("matching.views.record_mission_progress")
    @patch("matching.views.check_and_award_badges")
    def test_third_joiner_credited_individually(self, mock_badges, mock_mission):
        self.client.post(reverse("matching:join_group"))
        second_user = _make_user("joiner2@example.edu")
        _add_interests(second_user, ["Music", "Travel"])
        second_client = Client()
        second_client.force_login(second_user)
        second_client.post(reverse("matching:join_group"))

        third_user = _make_user("joiner3@example.edu")
        _add_interests(third_user, ["Music", "Travel"])
        third_client = Client()
        third_client.force_login(third_user)
        response = third_client.post(reverse("matching:join_group"))
        data = json.loads(response.content)

        self.assertTrue(data["formed"])
        self.assertEqual(len(data["members"]), 3)


class GroupStatusViewTests(TestCase):
    def setUp(self):
        self.user = _make_user("waiter@example.edu")
        self.client = Client()
        self.client.force_login(self.user)
        self.group = StudentGroup.objects.create(name="New Discussion Group")
        GroupMember.objects.create(group=self.group, user=self.user)

    # --- normal input ---
    def test_returns_not_formed_while_waiting_alone(self):
        response = self.client.get(reverse("matching:group_status", args=[self.group.id]))
        data = json.loads(response.content)

        self.assertFalse(data["formed"])

    # --- unexpected input: non-member checking a group's status ---
    def test_non_member_gets_403(self):
        outsider = _make_user("outsider@example.edu")
        outsider_client = Client()
        outsider_client.force_login(outsider)

        response = outsider_client.get(reverse("matching:group_status", args=[self.group.id]))

        self.assertEqual(response.status_code, 403)

    # --- unexpected input: nonexistent group id ---
    def test_nonexistent_group_returns_404(self):
        response = self.client.get(reverse("matching:group_status", args=[999999]))

        self.assertEqual(response.status_code, 404)


class CancelGroupWaitViewTests(TestCase):
    def setUp(self):
        self.user = _make_user("waiter@example.edu")
        self.client = Client()
        self.client.force_login(self.user)
        self.group = StudentGroup.objects.create(name="New Discussion Group")
        GroupMember.objects.create(group=self.group, user=self.user)

    # --- normal input ---
    def test_cancels_wait_while_alone(self):
        response = self.client.post(reverse("matching:cancel_group_wait", args=[self.group.id]))
        data = json.loads(response.content)

        self.assertTrue(data["ok"])
        gm = GroupMember.objects.get(group=self.group, user=self.user)
        self.assertIsNotNone(gm.left_at)

    # --- behavior: cannot cancel once the group has already formed ---
    def test_cannot_cancel_once_group_already_formed(self):
        second_user = _make_user("joiner2@example.edu")
        GroupMember.objects.create(group=self.group, user=second_user)

        response = self.client.post(reverse("matching:cancel_group_wait", args=[self.group.id]))
        data = json.loads(response.content)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(data["ok"])


class MyPendingStateViewTests(TestCase):
    def setUp(self):
        self.user = _make_user("checker@example.edu")
        self.client = Client()
        self.client.force_login(self.user)

    # --- boundary: no pending state at all ---
    def test_no_pending_state_returns_all_nulls(self):
        response = self.client.get(reverse("matching:my_pending_state"))
        data = json.loads(response.content)

        self.assertIsNone(data["friend_request_id"])
        self.assertIsNone(data["waiting_group_id"])

    # --- normal input: pending friend request recovered ---
    def test_recovers_pending_friend_request(self):
        recipient = _make_user("recipient@example.edu")
        mr = MatchRequest.objects.create(requester=self.user, recipient=recipient, status="pending")

        response = self.client.get(reverse("matching:my_pending_state"))
        data = json.loads(response.content)

        self.assertEqual(data["friend_request_id"], mr.id)

    # --- normal input: waiting-alone group recovered ---
    def test_recovers_waiting_group(self):
        group = StudentGroup.objects.create(name="New Discussion Group")
        GroupMember.objects.create(group=group, user=self.user)

        response = self.client.get(reverse("matching:my_pending_state"))
        data = json.loads(response.content)

        self.assertEqual(data["waiting_group_id"], group.id)


class BlockUserViewTests(TestCase):
    def setUp(self):
        self.user = _make_user("blocker@example.edu")
        self.other = _make_user("target@example.edu")
        self.client = Client()
        self.client.force_login(self.user)

    # --- normal input ---
    def test_creates_block_row(self):
        self.client.post(reverse("matching:block_user", args=[self.other.id]))

        self.assertTrue(Block.objects.filter(blocker=self.user, blocked=self.other).exists())

    # --- behavior: cascades to end an active connection ---
    def test_ends_active_connection_between_the_two(self):
        mr = MatchRequest.objects.create(requester=self.user, recipient=self.other, status="accepted")
        connection = Connection.objects.create(
            match_request=mr, user_a=self.user, user_b=self.other, status="active",
        )

        self.client.post(reverse("matching:block_user", args=[self.other.id]))

        connection.refresh_from_db()
        self.assertEqual(connection.status, "ended")
        self.assertEqual(connection.ended_reason, "block")

    # --- boundary: idempotent, blocking twice does not error or duplicate ---
    def test_blocking_same_user_twice_does_not_error(self):
        self.client.post(reverse("matching:block_user", args=[self.other.id]))
        response = self.client.post(reverse("matching:block_user", args=[self.other.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Block.objects.filter(blocker=self.user, blocked=self.other).count(), 1)

    # --- unexpected input: cannot block yourself ---
    def test_cannot_block_self(self):
        response = self.client.post(reverse("matching:block_user", args=[self.user.id]))
        data = json.loads(response.content)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(data["ok"])

    # --- unexpected input: nonexistent target user id ---
    def test_nonexistent_target_returns_404(self):
        response = self.client.post(reverse("matching:block_user", args=[999999]))

        self.assertEqual(response.status_code, 404)
