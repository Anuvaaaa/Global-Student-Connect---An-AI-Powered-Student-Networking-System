from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from ai_agents.models import SafetyFlag
from chat.models import Message, MessageTranslation
from chat.tests.factories import (
    make_connection, make_direct_conversation, make_profile,
    make_university, make_user,
)


def _safety_ok():
    return {'action': 'allow', 'severity': 'low', 'category': 'other', 'reasoning': '', 'stage': 'success'}


def _safety_auto_block():
    return {'action': 'auto_block', 'severity': 'high', 'category': 'harassment',
            'reasoning': 'flagged content', 'stage': 'success'}


def _safety_queue_review():
    return {'action': 'queue_human_review', 'severity': 'medium', 'category': 'spam',
            'reasoning': 'borderline', 'stage': 'success'}


def _safety_fallback():
    return {'action': 'allow', 'severity': 'low', 'category': 'other', 'reasoning': '', 'stage': 'error_fallback'}


class SendMessageViewTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        make_profile(self.alice, display_name='Alice')
        make_profile(self.bob, display_name='Bob')
        self.connection = make_connection(self.alice, self.bob)
        self.conversation = make_direct_conversation(self.connection)
        self.client.force_login(self.alice)
        self.url = reverse('chat:send_message', args=[self.conversation.id])

    def test_normal_input_sends_message(self):
        # normal input
        with patch('chat.views.check_message', return_value=_safety_ok()):
            response = self.client.post(self.url, {'text': 'Hello Bob'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertTrue(Message.objects.filter(text='Hello Bob').exists())

    def test_empty_text_rejected_before_reaching_safety_check(self):
        # boundary: empty string fails MessageForm validation
        with patch('chat.views.check_message') as mock_check:
            response = self.client.post(self.url, {'text': ''})
        self.assertEqual(response.status_code, 400)
        mock_check.assert_not_called()

    def test_exactly_500_chars_accepted(self):
        # boundary: maximum length
        with patch('chat.views.check_message', return_value=_safety_ok()):
            response = self.client.post(self.url, {'text': 'a' * 500})
        self.assertEqual(response.status_code, 200)

    def test_501_chars_rejected(self):
        # boundary: one over maximum
        with patch('chat.views.check_message') as mock_check:
            response = self.client.post(self.url, {'text': 'a' * 501})
        self.assertEqual(response.status_code, 400)
        mock_check.assert_not_called()

    def test_auto_block_prevents_message_from_saving(self):
        # behavior: auto_block must never persist the message, and must
        # log a SafetyFlag with no linked message (blocked_text instead)
        with patch('chat.views.check_message', return_value=_safety_auto_block()):
            response = self.client.post(self.url, {'text': 'bad content'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Message.objects.filter(text='bad content').exists())
        flag = SafetyFlag.objects.get(user=self.alice)
        self.assertIsNone(flag.message)
        self.assertEqual(flag.blocked_text, 'bad content')

    def test_queue_human_review_still_sends_message(self):
        # behavior: queue_human_review sends the message AND creates a
        # SafetyFlag linked to the saved message
        with patch('chat.views.check_message', return_value=_safety_queue_review()):
            response = self.client.post(self.url, {'text': 'borderline content'})
        self.assertEqual(response.status_code, 200)
        message = Message.objects.get(text='borderline content')
        flag = SafetyFlag.objects.get(user=self.alice)
        self.assertEqual(flag.message, message)

    def test_safety_agent_fallback_includes_notice(self):
        # unexpected input (upstream failure): Gemini unreachable — message
        # still sends, response carries the "napping" notice
        with patch('chat.views.check_message', return_value=_safety_fallback()):
            response = self.client.post(self.url, {'text': 'hello during outage'})
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertIn('safety_notice', data)

    def test_non_participant_cannot_send(self):
        # unexpected input: authenticated user who isn't in this conversation
        eve = make_user('eve', university=self.uni)
        self.client.force_login(eve)
        with patch('chat.views.check_message', return_value=_safety_ok()) as mock_check:
            response = self.client.post(self.url, {'text': 'hi'})
        self.assertEqual(response.status_code, 403)
        mock_check.assert_not_called()

    def test_ended_connection_rejects_send(self):
        # behavior: connection must be active to send
        self.connection.status = 'ended'
        self.connection.save()
        with patch('chat.views.check_message', return_value=_safety_ok()) as mock_check:
            response = self.client.post(self.url, {'text': 'hi'})
        self.assertEqual(response.status_code, 403)
        mock_check.assert_not_called()

    def test_get_request_not_allowed(self):
        # unexpected input: view is POST-only
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_send_does_not_eagerly_translate_for_recipient(self):
        # behavior: translation for an auto-translate recipient must NOT
        # happen inside send_message_view — that used to add a second
        # blocking Gemini call to every send. poll_messages_view/
        # conversation_view already translate lazily when the recipient
        # actually views, so send should stay fast regardless of the
        # recipient's translate settings.
        self.bob.profile.auto_translate = True
        self.bob.profile.translate_into = 'Bengali'
        self.bob.profile.save()

        with patch('chat.views.check_message', return_value=_safety_ok()), \
             patch('chat.views.translate_message') as mock_translate:
            self.client.post(self.url, {'text': 'hello'})

        mock_translate.assert_not_called()


class PollMessagesViewTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        make_profile(self.alice, display_name='Alice')
        make_profile(self.bob, display_name='Bob')
        self.connection = make_connection(self.alice, self.bob)
        self.conversation = make_direct_conversation(self.connection)
        self.client.force_login(self.alice)
        self.url = reverse('chat:poll_messages', args=[self.conversation.id])

    def test_normal_input_returns_only_new_messages(self):
        # normal input
        m1 = Message.objects.create(conversation=self.conversation, sender=self.bob, text='first')
        response = self.client.get(self.url, {'since': m1.id})
        self.assertEqual(response.json()['messages'], [])

        m2 = Message.objects.create(conversation=self.conversation, sender=self.bob, text='second')
        response = self.client.get(self.url, {'since': m1.id})
        data = response.json()
        self.assertEqual(len(data['messages']), 1)
        self.assertEqual(data['messages'][0]['id'], m2.id)

    def test_since_zero_returns_all_messages(self):
        # boundary: since=0 (default) returns the full history
        Message.objects.create(conversation=self.conversation, sender=self.bob, text='a')
        Message.objects.create(conversation=self.conversation, sender=self.bob, text='b')
        response = self.client.get(self.url)
        self.assertEqual(len(response.json()['messages']), 2)

    def test_non_numeric_since_falls_back_to_zero(self):
        # unexpected/invalid input: garbage since value must not 500
        Message.objects.create(conversation=self.conversation, sender=self.bob, text='a')
        response = self.client.get(self.url, {'since': 'not-a-number'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['messages']), 1)

    def test_marks_new_incoming_messages_read(self):
        # behavior
        msg = Message.objects.create(conversation=self.conversation, sender=self.bob, text='hi', is_read=False)
        self.client.get(self.url)
        msg.refresh_from_db()
        self.assertTrue(msg.is_read)

    def test_blocked_conversation_returns_403(self):
        # unexpected input
        from matching.models import Block
        Block.objects.create(blocker=self.alice, blocked=self.bob)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)


class TranslateMessageViewTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        make_profile(self.alice, display_name='Alice', translate_into='French')
        make_profile(self.bob, display_name='Bob')
        self.connection = make_connection(self.alice, self.bob)
        self.conversation = make_direct_conversation(self.connection)
        self.message = Message.objects.create(conversation=self.conversation, sender=self.bob, text='Hola')
        self.client.force_login(self.alice)
        self.url = reverse('chat:translate_message', args=[self.conversation.id, self.message.id])

    def test_normal_input_returns_translated_text(self):
        # normal input
        with patch('chat.utils.translate_text', return_value={'translated_text': 'Bonjour', 'stage': 'success'}):
            response = self.client.post(self.url)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['translated_text'], 'Bonjour')
        self.assertNotIn('translation_notice', data)

    def test_pipeline_fallback_includes_notice(self):
        # unexpected input (upstream failure): breaker open / API failure
        with patch('chat.utils.translate_text', return_value={'translated_text': 'Hola', 'stage': 'error_fallback'}):
            response = self.client.post(self.url)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertIn('translation_notice', data)

    def test_nonexistent_message_returns_404(self):
        # boundary/unexpected input
        url = reverse('chat:translate_message', args=[self.conversation.id, 999999])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_get_request_not_allowed(self):
        # unexpected input: view is POST-only
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_repeated_translate_reuses_cached_row(self):
        # behavior: idempotent — second call doesn't hit the pipeline again
        with patch('chat.utils.translate_text', return_value={'translated_text': 'Bonjour', 'stage': 'success'}) as mock_t:
            self.client.post(self.url)
            self.client.post(self.url)
        mock_t.assert_called_once()
        self.assertEqual(MessageTranslation.objects.filter(message=self.message).count(), 1)
