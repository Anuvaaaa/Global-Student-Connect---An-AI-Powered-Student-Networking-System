from datetime import timedelta

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import NudgeLog, SafetyFlag


@admin.register(SafetyFlag)
class SafetyFlagAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'category', 'severity', 'status',
        'flagged_content_preview', 'user_status', 'created_at',
    )
    list_filter = ('status', 'severity', 'category', 'created_at')
    search_fields = ('user__email', 'ai_reasoning', 'blocked_text')
    readonly_fields = ('flagged_content',)
    actions = ['suspend_flagged_users', 'ban_flagged_users', 'lift_suspension']

    def flagged_content(self, obj):
        """Full flagged text plus Gemini's reasoning, for the review screen."""
        kind, text = obj.flagged_content_source()
        return format_html(
            "<p><b>{}:</b><br>{}</p><p><b>AI reasoning:</b><br>{}</p>",
            kind.replace("_", " ").title(),
            text or "(no text)",
            obj.ai_reasoning or "(none provided)",
        )
    flagged_content.short_description = "Flagged content & AI reasoning"

    def flagged_content_preview(self, obj):
        """Short one-line version for the list view."""
        _, text = obj.flagged_content_source()
        if not text:
            return "(no text)"
        return text if len(text) <= 60 else text[:57] + "..."
    flagged_content_preview.short_description = "Content"

    def user_status(self, obj):
        u = obj.user
        if u is None:
            return "—"
        if u.is_banned:
            return format_html('<span style="color:red;">{}</span>', "Banned")
        if u.suspended_until and u.suspended_until > timezone.now():
            local_time = timezone.localtime(u.suspended_until)
            return format_html(
                '<span style="color:orange;">Suspended until {}</span>',
                local_time.strftime('%Y-%m-%d %H:%M')
            )
        return "Active"
    user_status.short_description = "Account Status"

    @admin.action(description="Suspend selected users for 7 days")
    def suspend_flagged_users(self, request, queryset):
        count = 0
        for flag in queryset:
            if flag.user is None:
                continue
            flag.user.suspended_until = timezone.now() + timedelta(days=7)
            flag.user.save(update_fields=['suspended_until'])
            flag.status = 'reviewed'
            flag.save(update_fields=['status'])
            count += 1
        self.message_user(request, f"{count} user(s) suspended for 7 days.")

    @admin.action(description="Ban selected users permanently")
    def ban_flagged_users(self, request, queryset):
        count = 0
        for flag in queryset:
            if flag.user is None:
                continue
            flag.user.is_banned = True
            flag.user.save(update_fields=['is_banned'])
            flag.status = 'reviewed'
            flag.save(update_fields=['status'])
            count += 1
        self.message_user(request, f"{count} user(s) banned.")

    @admin.action(description="Lift suspension for selected users")
    def lift_suspension(self, request, queryset):
        count = 0
        for flag in queryset:
            if flag.user is None:
                continue
            flag.user.suspended_until = None
            flag.user.is_banned = False
            flag.user.save(update_fields=['suspended_until', 'is_banned'])
            count += 1
        self.message_user(request, f"Suspension/ban lifted for {count} user(s).")


@admin.register(NudgeLog)
class NudgeLogAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'nudge_type', 'target_display',
        'progress_pct', 'message_preview', 'sent_at',
    )
    list_filter = ('nudge_type', 'sent_at')
    search_fields = ('user__email', 'message_text', 'badge__name', 'mission__name')
    readonly_fields = ('user', 'nudge_type', 'badge', 'mission', 'progress_pct', 'message_text', 'sent_at')

    def target_display(self, obj):
        """Whichever of badge/mission is actually set — mirrors the
        __str__ fallback already defined on NudgeLog itself, so the
        list view and the model's own string representation never
        disagree about which target a row is showing."""
        return obj.badge.name if obj.badge_id else obj.mission.name
    target_display.short_description = "Target"

    def message_preview(self, obj):
        text = obj.message_text
        return text if len(text) <= 60 else text[:57] + "..."
    message_preview.short_description = "Message"

    def has_add_permission(self, request):
        # NudgeLog rows only ever come from the Nudge agent pipeline —
        # creating one by hand here wouldn't correspond to a real
        # nudge actually having been sent, so this is read-only, same
        # spirit as SafetyFlag's readonly_fields but for the whole model.
        return False
