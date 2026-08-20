from django.test import TestCase
from django.urls import reverse

from chat.models import Message
from chat.tests.factories import (
    make_connection, make_direct_conversation, make_group,
    make_group_conversation, make_group_member, make_university, make_user,
)


class InboxViewTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        self.client.force_login(self.alice)

    def test_requires_login(self):
        # behavior: anonymous access redirects to login
        self.client.logout()
        response = self.client.get(reverse('chat:inbox'))
        self.assertEqual(response.status_code, 302)

    def test_normal_input_no_conversations_yet(self):
        # boundary: zero conversations — empty-state path
        response = self.client.get(reverse('chat:inbox'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['conversations'], [])

    def test_active_direct_conversation_appears(self):
        # normal input
        connection = make_connection(self.alice, self.bob)
        conv = make_direct_conversation(connection)
        Message.objects.create(conversation=conv, sender=self.bob, text='hey')

        response = self.client.get(reverse('chat:inbox'))
        ids = [item['conversation_id'] for item in response.context['conversations']]
        self.assertIn(conv.id, ids)

    def test_ended_direct_conversation_excluded(self):
        # categories of input: connection status != active must be filtered out
        connection = make_connection(self.alice, self.bob, status='ended')
        conv = make_direct_conversation(connection)

        response = self.client.get(reverse('chat:inbox'))
        ids = [item['conversation_id'] for item in response.context['conversations']]
        self.assertNotIn(conv.id, ids)

    def test_left_group_excluded_from_inbox(self):
        # categories of input: group membership with left_at set must be excluded
        from django.utils import timezone
        from matching.models import GroupMember

        group = make_group()
        conv = make_group_conversation(group)
        alice_membership = make_group_member(group, self.alice, left_at=None)
        make_group_member(group, self.bob)  # unrelated active member

        alice_membership.left_at = timezone.now()
        alice_membership.save()

        response = self.client.get(reverse('chat:inbox'))
        ids = [item['conversation_id'] for item in response.context['conversations']]
        self.assertNotIn(conv.id, ids)

    def test_unread_count_excludes_own_messages(self):
        # behavior: unread count should never include the viewer's own sent messages
        connection = make_connection(self.alice, self.bob)
        conv = make_direct_conversation(connection)
        Message.objects.create(conversation=conv, sender=self.alice, text='from me', is_read=False)
        Message.objects.create(conversation=conv, sender=self.bob, text='from bob', is_read=False)

        response = self.client.get(reverse('chat:inbox'))
        item = next(i for i in response.context['conversations'] if i['conversation_id'] == conv.id)
        self.assertEqual(item['unread'], 1)


class InboxPollViewTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        self.client.force_login(self.alice)

    def test_normal_input_returns_json_ok(self):
        # normal input, behavior: JSON contract used by chat.html's poll loop
        response = self.client.get(reverse('chat:inbox_poll'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertIsInstance(data['conversations'], list)

    def test_requires_login(self):
        # unexpected input: unauthenticated poll request
        self.client.logout()
        response = self.client.get(reverse('chat:inbox_poll'))
        self.assertEqual(response.status_code, 302)

    def test_payload_uses_relative_time_display(self):
        # behavior: sent_at_display is a "timesince ... ago" string, not a raw datetime
        connection = make_connection(self.alice, self.bob)
        conv = make_direct_conversation(connection)
        Message.objects.create(conversation=conv, sender=self.bob, text='hi')

        response = self.client.get(reverse('chat:inbox_poll'))
        item = next(i for i in response.json()['conversations'] if i['conversation_id'] == conv.id)
        self.assertTrue(item['sent_at_display'].endswith('ago'))
