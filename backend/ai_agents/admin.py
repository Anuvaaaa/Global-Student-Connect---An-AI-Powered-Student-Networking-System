from datetime import timedelta

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import SafetyFlag


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
        text = obj.message.text if obj.message else obj.blocked_text
        source = "Sent message" if obj.message else "Auto-blocked (never sent)"
        return format_html(
            "<p><b>{}:</b><br>{}</p><p><b>AI reasoning:</b><br>{}</p>",
            source, text or "(no text)", obj.ai_reasoning or "(none provided)",
        )
    flagged_content.short_description = "Flagged content & AI reasoning"

    def flagged_content_preview(self, obj):
        """Short one-line version for the list view."""
        text = obj.message.text if obj.message else obj.blocked_text
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
