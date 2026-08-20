from django.conf import settings
from django.db import models

from matching.models import Connection, StudentGroup


class Conversation(models.Model):
    TYPE_CHOICES = [('direct', 'direct'), ('group', 'group')]
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    connection = models.OneToOneField(Connection, on_delete=models.CASCADE, null=True, blank=True)
    group = models.OneToOneField(StudentGroup, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)


class MessageTranslation(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='translations')
    language = models.CharField(max_length=50)
    translated_text = models.TextField()
    is_fallback = models.BooleanField(default=False)