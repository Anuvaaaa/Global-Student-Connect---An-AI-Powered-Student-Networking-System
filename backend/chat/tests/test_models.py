from django.db import IntegrityError, transaction
from django.test import TestCase

from chat.models import Conversation, Message, MessageTranslation
from chat.tests.factories import (
    make_connection, make_direct_conversation, make_group,
    make_group_conversation, make_university, make_user,
)


class ConversationModelTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)

    def test_direct_conversation_normal_creation(self):
        # normal input
        connection = make_connection(self.alice, self.bob)
        conv = make_direct_conversation(connection)
        self.assertEqual(conv.type, 'direct')
        self.assertEqual(conv.connection, connection)
        self.assertIsNone(conv.group)

    def test_group_conversation_normal_creation(self):
        # normal input, second category of the type field (group vs direct)
        group = make_group()
        conv = make_group_conversation(group)
        self.assertEqual(conv.type, 'group')
        self.assertEqual(conv.group, group)
        self.assertIsNone(conv.connection)

    def test_connection_field_unique_per_conversation(self):
        # boundary / behavior: schema says connection FK is one-to-one —
        # a second Conversation can't reuse the same Connection
        connection = make_connection(self.alice, self.bob)
        make_direct_conversation(connection)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Conversation.objects.create(type='direct', connection=connection)

    def test_group_field_unique_per_conversation(self):
        # boundary / behavior: same one-to-one constraint on group
        group = make_group()
        make_group_conversation(group)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Conversation.objects.create(type='group', group=group)


class MessageModelTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        self.connection = make_connection(self.alice, self.bob)
        self.conversation = make_direct_conversation(self.connection)

    def test_message_normal_creation_defaults_unread(self):
        # normal input + behavior: is_read defaults to False
        msg = Message.objects.create(
            conversation=self.conversation, sender=self.alice, text='Hello Bob'
        )
        self.assertFalse(msg.is_read)
        self.assertIsNotNone(msg.sent_at)

    def test_message_empty_text_allowed_at_model_level(self):
        # boundary: empty string — model itself has no min-length
        # constraint (that's enforced by MessageForm, tested separately),
        # so the model layer must accept it without raising
        msg = Message.objects.create(conversation=self.conversation, sender=self.alice, text='')
        self.assertEqual(msg.text, '')

    def test_message_without_conversation_raises(self):
        # unexpected/invalid input: conversation FK is required (no null=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Message.objects.create(conversation=None, sender=self.alice, text='orphan')

    def test_message_ordering_by_sent_at(self):
        # behavior: messages.order_by('sent_at') used throughout views
        # relies on insertion order being preserved
        first = Message.objects.create(conversation=self.conversation, sender=self.alice, text='first')
        second = Message.objects.create(conversation=self.conversation, sender=self.bob, text='second')
        ordered = list(self.conversation.messages.order_by('sent_at'))
        self.assertEqual(ordered, [first, second])


class MessageTranslationModelTests(TestCase):
    def setUp(self):
        self.uni = make_university()
        self.alice = make_user('alice', university=self.uni)
        self.bob = make_user('bob', university=self.uni)
        connection = make_connection(self.alice, self.bob)
        self.conversation = make_direct_conversation(connection)
        self.message = Message.objects.create(
            conversation=self.conversation, sender=self.alice, text='Hola'
        )

    def test_translation_normal_creation(self):
        # normal input
        t = MessageTranslation.objects.create(
            message=self.message, language='English', translated_text='Hello'
        )
        self.assertEqual(t.message, self.message)
        self.assertEqual(t.translated_text, 'Hello')

    def test_is_fallback_defaults_false(self):
        # behavior: a row created without specifying is_fallback must
        # default to False (i.e. "this is a real translation" is the
        # assumed case unless explicitly marked otherwise)
        t = MessageTranslation.objects.create(
            message=self.message, language='English', translated_text='Hello'
        )
        self.assertFalse(t.is_fallback)

    def test_is_fallback_can_be_set_true(self):
        # categories of input: explicit fallback row
        t = MessageTranslation.objects.create(
            message=self.message, language='English', translated_text='Hola', is_fallback=True
        )
        self.assertTrue(t.is_fallback)

    def test_multiple_languages_for_same_message(self):
        # categories of input: two different target languages for the
        # same message must coexist as separate rows
        MessageTranslation.objects.create(message=self.message, language='English', translated_text='Hello')
        MessageTranslation.objects.create(message=self.message, language='French', translated_text='Bonjour')
        self.assertEqual(self.message.translations.count(), 2)

    def test_translation_without_message_raises(self):
        # unexpected/invalid input: message FK is required
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MessageTranslation.objects.create(message=None, language='English', translated_text='Hello')
