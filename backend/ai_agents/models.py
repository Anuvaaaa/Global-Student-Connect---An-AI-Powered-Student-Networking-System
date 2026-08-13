from django.db import models
from django.conf import settings

# NOTE: adjust these import paths to match where your teammates' models
# actually live. Message -> chat app, Report -> moderation app.
from chat.models import Message
from moderation.models import Report


class SafetyFlag(models.Model):
    """Supports the Safety agent."""

    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]
    CATEGORY_CHOICES = [
        ("harassment", "Harassment"),
        ("spam", "Spam"),
        ("inappropriate_content", "Inappropriate Content"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("reviewed", "Reviewed"),
        ("dismissed", "Dismissed"),
    ]

    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="safety_flags"
    )
    report = models.ForeignKey(
        Report, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="safety_flags",
        help_text="Set only if this flag corroborates an existing human-filed report.",
    )
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    ai_reasoning = models.TextField(help_text="Gemini's explanation for the flag.")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"SafetyFlag(message={self.message_id}, severity={self.severity}, status={self.status})"


class NudgeLog(models.Model):
    """Supports the Nudge agent."""

    NUDGE_TYPE_CHOICES = [
        ("incomplete_profile", "Incomplete Profile"),
        ("inactive_matching", "Inactive Matching"),
        ("streak_reminder", "Streak Reminder"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="nudge_logs"
    )
    nudge_type = models.CharField(max_length=30, choices=NUDGE_TYPE_CHOICES)
    message_text = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    was_dismissed = models.BooleanField(null=True, blank=True)

    def __str__(self):
        return f"NudgeLog(user={self.user_id}, type={self.nudge_type})"


class AssistantThread(models.Model):
    """Supports the Platform Assistant agent."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_threads"
    )
    title = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title or f"AssistantThread(user={self.user_id})"


class AssistantMessage(models.Model):
    """Supports the Platform Assistant agent."""

    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
    ]

    thread = models.ForeignKey(
        AssistantThread, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"AssistantMessage(thread={self.thread_id}, role={self.role})"
