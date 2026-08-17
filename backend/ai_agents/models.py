# TARGET PATH: ai_agents/models.py
from django.db import models
from django.conf import settings

# NOTE: adjust these import paths to match where your teammates' models
# actually live. Message -> chat app, Report -> moderation app,
# Post/Comment -> social app, Badge/Mission -> engagement app.
from chat.models import Message
from moderation.models import Report
from social.models import Post, Comment
from engagement.models import Badge, Mission


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

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="safety_flags",
        null=True, blank=True,
        help_text="Who sent the flagged content. Set directly rather than "
                   "relying on message.sender/post.user/comment.user, since "
                   "those are all null for auto-blocked content — this keeps "
                   "admin actions (suspend/ban) working the same way "
                   "regardless of which content type was flagged.",
    )
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="safety_flags",
        null=True, blank=True,
        help_text="Set when the flagged content was a chat message. Null "
                   "when this flag came from an auto-blocked message — "
                   "that message was never saved, see blocked_text instead.",
    )
    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name="safety_flags",
        null=True, blank=True,
        help_text="Set when the flagged content was a social post. Null "
                   "when auto-blocked — the post was never saved, see "
                   "blocked_text instead.",
    )
    comment = models.ForeignKey(
        Comment, on_delete=models.CASCADE, related_name="safety_flags",
        null=True, blank=True,
        help_text="Set when the flagged content was a comment. Null when "
                   "auto-blocked — the comment was never saved, see "
                   "blocked_text instead.",
    )
    blocked_text = models.TextField(
        null=True, blank=True,
        help_text="Snapshot of the flagged text. Only set for auto-blocked "
                   "content (where message/post/comment are all null) — "
                   "otherwise the flagged content is recoverable via "
                   "whichever FK is set.",
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

    def flagged_content_source(self):
        """
        Returns (kind, text) for whichever content type this flag actually
        points to. Centralizes the message/post/comment/blocked_text
        fallback chain so admin.py and __str__ don't duplicate it.
        """
        if self.message_id:
            return "message", self.message.text
        if self.post_id:
            return "post", self.post.text
        if self.comment_id:
            return "comment", self.comment.text
        return "auto_blocked", self.blocked_text

    def __str__(self):
        kind, _ = self.flagged_content_source()
        return f"SafetyFlag({kind}, severity={self.severity}, status={self.status})"


class NudgeLog(models.Model):
    """
    Supports the Nudge agent.

    SCHEMA CHANGE (post-handoff): nudge_type no longer covers
    incomplete_profile/inactive_matching/streak_reminder — those were
    speculative values for a periodic-nudge design that was never
    built. Nudge is scoped to badge/mission progress only, event-driven
    off engagement/signals.py's badge_progress_updated and
    mission_progress_updated signals (see engagement/utils.py for
    where those fire). badge/mission/progress_pct are new fields
    needed for that: badge/mission identify WHAT the nudge was about
    (required for the CheckConstraint below and for per-badge/mission
    rate-limiting in ai_agents/services/nudge_service.py), and
    progress_pct snapshots progress at nudge time so rate-limiting can
    compare against it without re-querying UserMissionProgress/
    UserEngagement at read time.
    """

    NUDGE_TYPE_CHOICES = [
        ("badge_progress", "Badge Progress"),
        ("mission_progress", "Mission Progress"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="nudge_logs"
    )
    nudge_type = models.CharField(max_length=20, choices=NUDGE_TYPE_CHOICES)
    badge = models.ForeignKey(
        Badge, on_delete=models.CASCADE, null=True, blank=True,
        related_name="nudge_logs",
        help_text="Set when nudge_type is badge_progress. Exactly one of "
                   "badge/mission must be set — enforced by the "
                   "CheckConstraint below.",
    )
    mission = models.ForeignKey(
        Mission, on_delete=models.CASCADE, null=True, blank=True,
        related_name="nudge_logs",
        help_text="Set when nudge_type is mission_progress. Exactly one of "
                   "badge/mission must be set — enforced by the "
                   "CheckConstraint below.",
    )
    progress_pct = models.IntegerField(
        help_text="Progress (0-100) toward the badge/mission at the moment "
                   "this nudge was sent. Used for delta-based rate-limiting "
                   "— see ai_agents/services/nudge_service.py.",
    )
    message_text = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(badge__isnull=False, mission__isnull=True)
                    | models.Q(badge__isnull=True, mission__isnull=False)
                ),
                name="nudgelog_exactly_one_of_badge_or_mission",
            )
        ]

    def __str__(self):
        target = self.badge.name if self.badge_id else self.mission.name
        return f"NudgeLog(user={self.user_id}, type={self.nudge_type}, target={target})"


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
