from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from chat.models import Message
from chat.tests.factories import (
    make_connection, make_direct_conversation, make_group,
    make_group_conversation, make_group_member, make_profile,
    make_university, make_user,
)
from matching.models import Block


class DirectConversationViewTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        make_profile(self.alice, display_name='Alice')
        make_profile(self.bob, display_name='Bob')
        self.connection = make_connection(self.alice, self.bob)
        self.conversation = make_direct_conversation(self.connection)
        self.client.force_login(self.alice)

    def test_normal_input_renders_conversation(self):
        # normal input
        response = self.client.get(reverse('chat:conversation', args=[self.conversation.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['other_name'], 'Bob')

    def test_non_participant_redirected_to_inbox(self):
        # unexpected input: a third user with no relation to this conversation
        eve = make_user('eve', university=self.uni)
        self.client.force_login(eve)
        response = self.client.get(reverse('chat:conversation', args=[self.conversation.id]))
        self.assertRedirects(response, reverse('chat:inbox'))

    def test_blocked_either_way_redirects_to_inbox(self):
        # behavior: symmetric block enforcement — even though Bob never
        # blocked Alice, Alice blocking Bob must still hide the conversation
        Block.objects.create(blocker=self.alice, blocked=self.bob)
        response = self.client.get(reverse('chat:conversation', args=[self.conversation.id]))
        self.assertRedirects(response, reverse('chat:inbox'))

    def test_nonexistent_conversation_returns_404(self):
        # boundary/unexpected input: conversation id that doesn't exist
        response = self.client.get(reverse('chat:conversation', args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_ended_connection_still_viewable_but_flagged_inactive(self):
        # categories of input: ended connection is viewable (history) but
        # connection_active must be False so the template disables sending
        self.connection.status = 'ended'
        self.connection.save()
        response = self.client.get(reverse('chat:conversation', args=[self.conversation.id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['connection_active'])

    def test_auto_translate_on_calls_translate_message_per_incoming_message(self):
        # behavior: when the viewer has auto_translate on, every message
        # NOT sent by them gets translated
        self.alice.profile.auto_translate = True
        self.alice.profile.translate_into = 'French'
        self.alice.profile.save()
        Message.objects.create(conversation=self.conversation, sender=self.bob, text='hi')

        with patch('chat.views.translate_message') as mock_translate:
            mock_translate.return_value = None
            self.client.get(reverse('chat:conversation', args=[self.conversation.id]))
        mock_translate.assert_called_once()

    def test_marks_incoming_unread_messages_as_read_on_view(self):
        # behavior: opening the conversation marks the other person's
        # unread messages as read, but never the viewer's own
        Message.objects.create(conversation=self.conversation, sender=self.bob, text='unread', is_read=False)
        mine = Message.objects.create(conversation=self.conversation, sender=self.alice, text='mine', is_read=False)

        self.client.get(reverse('chat:conversation', args=[self.conversation.id]))

        self.assertTrue(self.conversation.messages.get(sender=self.bob).is_read)
        mine.refresh_from_db()
        self.assertFalse(mine.is_read)


class GroupConversationViewTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        make_profile(self.alice, display_name='Alice')
        make_profile(self.bob, display_name='Bob')
        self.group = make_group(name='Study Group')
        self.conversation = make_group_conversation(self.group)
        make_group_member(self.group, self.alice)
        make_group_member(self.group, self.bob)
        self.client.force_login(self.alice)

    def test_normal_input_renders_group_conversation(self):
        # normal input
        response = self.client.get(reverse('chat:conversation', args=[self.conversation.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['group'], self.group)
        self.assertEqual(response.context['member_count'], 2)

    def test_non_member_redirected_to_inbox(self):
        # unexpected input: user who never joined this group
        eve = make_user('eve', university=self.uni)
        self.client.force_login(eve)
        response = self.client.get(reverse('chat:conversation', args=[self.conversation.id]))
        self.assertRedirects(response, reverse('chat:inbox'))

    def test_zero_other_members_edge_case(self):
        # boundary: solo group — only the viewer is an active member
        solo_group = make_group(name='Solo')
        solo_conv = make_group_conversation(solo_group)
        make_group_member(solo_group, self.alice)

        response = self.client.get(reverse('chat:conversation', args=[solo_conv.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['other_members'], [])

    def test_left_member_excluded_from_other_members_list(self):
        # categories of input: a member who left shouldn't appear in the
        # roster shown to remaining members
        from django.utils import timezone
        carol = make_user('carol', university=self.uni)
        make_profile(carol, display_name='Carol')
        membership = make_group_member(self.group, carol)
        membership.left_at = timezone.now()
        membership.save()

        response = self.client.get(reverse('chat:conversation', args=[self.conversation.id]))
        names = [m['name'] for m in response.context['other_members']]
        self.assertNotIn('Carol', names)

    def test_deleted_member_shows_anonymized_identity(self):
        # unexpected/invalid input: a soft-deleted group member must
        # never leak their real name/university/country to the rest of the group
        self.bob.is_deleted = True
        self.bob.save()

        response = self.client.get(reverse('chat:conversation', args=[self.conversation.id]))
        names = [m['name'] for m in response.context['other_members']]
        self.assertIn('Deleted Student', names)
        self.assertNotIn('Bob', names)
