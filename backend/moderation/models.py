from django.conf import settings
from django.db import models

from chat.models import Conversation


class Report(models.Model):
    STATUS_CHOICES = [
        ('pending', 'pending'), ('reviewed', 'reviewed'),
        ('dismissed', 'dismissed'), ('action_taken', 'action_taken'),
    ]
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports_filed'
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports_against'
    )
    reason = models.CharField(max_length=255)
    context_conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reports_reviewed'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
