from django.conf import settings
from django.db import models


class Notification(models.Model):
    TYPE_CHOICES = [
        ('match', 'match'), ('group', 'group'), ('message', 'message'),
        ('badge', 'badge'), ('mission', 'mission'), ('system', 'system'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    cta_label = models.CharField(max_length=100, null=True, blank=True)
    cta_href = models.CharField(max_length=255, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class UserEngagement(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='engagement')
    messages_sent = models.IntegerField(default=0)
    countries_connected = models.IntegerField(default=0)
    groups_joined = models.IntegerField(default=0)
    translations_used = models.IntegerField(default=0)
    comments_made = models.IntegerField(default=0)
    likes_given = models.IntegerField(default=0)
    conversation_count = models.IntegerField(default=0)
    last_daily_mission_date = models.DateField(null=True, blank=True)
    last_moment_posted_date = models.DateField(null=True, blank=True)


class Badge(models.Model):
    METRIC_CHOICES = [
        ('matches', 'matches'), ('messages_sent', 'messages_sent'),
        ('countries_connected', 'countries_connected'),
        ('groups_joined', 'groups_joined'), ('translations_used', 'translations_used'),
    ]
    TIER_CHOICES = [
        ('bronze', 'Bronze'), ('silver', 'Silver'), ('gold', 'Gold'),
    ]
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    threshold = models.IntegerField()
    metric = models.CharField(max_length=30, choices=METRIC_CHOICES)
    tier = models.CharField(max_length=10, choices=TIER_CHOICES)
    badge_group = models.CharField(max_length=100)  # e.g. "social_butterfly" — groups the 3 tiers together

    def __str__(self):
        return f"{self.name} ({self.get_tier_display()})"


class UserBadge(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE)
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'badge'], name='unique_user_badge')
        ]


class Mission(models.Model):
    FREQUENCY_CHOICES = [('daily', 'daily'), ('weekly', 'weekly')]
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES)
    target = models.IntegerField()
    linked_badge = models.ForeignKey(Badge, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.name


class UserMissionProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    mission = models.ForeignKey(Mission, on_delete=models.CASCADE)
    progress = models.IntegerField(default=0)
    period_start = models.DateField()
    completed_at = models.DateTimeField(null=True, blank=True)