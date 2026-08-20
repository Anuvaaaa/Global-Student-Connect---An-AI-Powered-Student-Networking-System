from django.test import TestCase
from django.urls import reverse

from chat.tests.factories import (
    make_connection, make_direct_conversation, make_group,
    make_group_conversation, make_group_member, make_university, make_user,
)
from matching.models import GroupMember


class EndChatViewTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        self.connection = make_connection(self.alice, self.bob)
        self.conversation = make_direct_conversation(self.connection)
        self.client.force_login(self.alice)
        self.url = reverse('chat:end_chat', args=[self.conversation.id])

    def test_normal_input_ends_active_connection(self):
        # normal input
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, 'ended')
        self.assertEqual(self.connection.ended_reason, 'manual_end')
        self.assertIsNotNone(self.connection.ended_at)

    def test_already_ended_connection_is_a_no_op(self):
        # boundary: ending an already-ended connection must not error or
        # overwrite ended_reason (e.g. a prior block)
        self.connection.status = 'ended'
        self.connection.ended_reason = 'block'
        self.connection.save()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.ended_reason, 'block')

    def test_non_participant_forbidden(self):
        # unexpected input
        eve = make_user('eve', university=self.uni)
        self.client.force_login(eve)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 403)

    def test_group_conversation_rejected(self):
        # unexpected/invalid input: end_chat only applies to direct conversations
        group = make_group()
        group_conv = make_group_conversation(group)
        make_group_member(group, self.alice)
        url = reverse('chat:end_chat', args=[group_conv.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)

    def test_get_request_not_allowed(self):
        # unexpected input
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_nonexistent_conversation_404(self):
        # boundary
        url = reverse('chat:end_chat', args=[999999])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)


class LeaveGroupViewTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        self.group = make_group()
        self.conversation = make_group_conversation(self.group)
        make_group_member(self.group, self.alice)
        make_group_member(self.group, self.bob)
        self.client.force_login(self.alice)
        self.url = reverse('chat:leave_group', args=[self.conversation.id])

    def test_normal_input_leaves_group(self):
        # normal input
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        membership = GroupMember.objects.get(group=self.group, user=self.alice)
        self.assertIsNotNone(membership.left_at)

    def test_already_left_returns_403(self):
        # boundary: leaving twice — second attempt finds no active membership
        self.client.post(self.url)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 403)

    def test_non_member_forbidden(self):
        # unexpected input: user never in this group
        eve = make_user('eve', university=self.uni)
        self.client.force_login(eve)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 403)

    def test_direct_conversation_rejected(self):
        # unexpected/invalid input: leave_group only applies to group conversations
        connection = make_connection(self.alice, self.bob)
        direct_conv = make_direct_conversation(connection)
        url = reverse('chat:leave_group', args=[direct_conv.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)

    def test_get_request_not_allowed(self):
        # unexpected input
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_last_remaining_member_can_still_leave(self):
        # boundary: leaving a group down to zero active members must not
        # be blocked by some implicit "can't be empty" rule
        self.client.force_login(self.bob)
        url = reverse('chat:leave_group', args=[self.conversation.id])
        self.client.post(url)
        self.client.force_login(self.alice)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
