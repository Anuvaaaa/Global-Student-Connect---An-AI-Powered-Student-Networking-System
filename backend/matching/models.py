from django.conf import settings
from django.db import models


class MatchRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'pending'), ('accepted', 'accepted'),
        ('declined', 'declined'), ('cancelled', 'cancelled'),
    ]
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_match_requests'
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_match_requests'
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    compatibility_score = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)


class Connection(models.Model):
    STATUS_CHOICES = [('active', 'active'), ('ended', 'ended')]
    ENDED_REASON_CHOICES = [
        ('manual_end', 'manual_end'), ('block', 'block'), ('report_action', 'report_action'),
    ]
    match_request = models.ForeignKey(MatchRequest, on_delete=models.CASCADE)
    user_a = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='connections_as_a')
    user_b = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='connections_as_b')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    ended_reason = models.CharField(max_length=20, choices=ENDED_REASON_CHOICES, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)


class Block(models.Model):
    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocks_made')
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocks_received')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['blocker', 'blocked'], name='unique_block')
        ]


class StudentGroup(models.Model):  # renamed from "Group" to avoid clashing with Django's built-in auth Group
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)


class GroupMember(models.Model):
    group = models.ForeignKey(StudentGroup, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)