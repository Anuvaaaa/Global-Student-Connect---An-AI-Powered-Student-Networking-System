from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from datetime import timedelta

from .models import Report
from chat.models import Message


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'reporter', 'reported_user', 'reason',
        'status', 'reported_user_status', 'created_at',
    )
    list_filter = ('status', 'created_at')
    search_fields = ('reporter__email', 'reported_user__email', 'reason')
    readonly_fields = ('recent_messages',)
    actions = ['suspend_reported_users', 'ban_reported_users', 'lift_suspension']

    def reported_user_status(self, obj):
        u = obj.reported_user
        if u.is_banned:
            return format_html('<span style="color:red;">{}</span>', "Banned")
        if u.suspended_until and u.suspended_until > timezone.now():
            local_time = timezone.localtime(u.suspended_until)
            return format_html(
                '<span style="color:orange;">Suspended until {}</span>',
                local_time.strftime('%Y-%m-%d %H:%M')
            )
        return "Active"
    reported_user_status.short_description = "Account Status"

    def recent_messages(self, obj):
        if not obj.context_conversation:
            return "No conversation linked to this report."

        messages = (
            Message.objects
            .filter(conversation=obj.context_conversation)
            .order_by('-sent_at')[:20]
        )
        if not messages:
            return "No messages found."

        rows_html = format_html_join(
            '',
            "<tr><td style='padding:4px 10px;'>{}</td>"
            "<td style='padding:4px 10px;'><b>{}</b></td>"
            "<td style='padding:4px 10px;'>{}</td></tr>",
            (
                (
                    m.sent_at.strftime('%Y-%m-%d %H:%M'),
                    "Deleted Student" if m.sender.is_deleted else m.sender.email,
                    m.text,
                )
                for m in messages
            )
        )
        return format_html(
            "<table style='border-collapse:collapse;'>"
            "<tr><th>Time</th><th>Sender</th><th>Message</th></tr>{}</table>",
            rows_html
        )
    recent_messages.short_description = "Last 20 messages in reported conversation"

    @admin.action(description="Suspend selected users for 7 days")
    def suspend_reported_users(self, request, queryset):
        count = 0
        for report in queryset:
            user = report.reported_user
            user.suspended_until = timezone.now() + timedelta(days=7)
            user.save(update_fields=['suspended_until'])
            report.status = 'action_taken'
            report.reviewed_by = request.user
            report.reviewed_at = timezone.now()
            report.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
            count += 1
        self.message_user(request, f"{count} user(s) suspended for 7 days.")

    @admin.action(description="Ban selected users permanently")
    def ban_reported_users(self, request, queryset):
        count = 0
        for report in queryset:
            user = report.reported_user
            user.is_banned = True
            user.save(update_fields=['is_banned'])
            report.status = 'action_taken'
            report.reviewed_by = request.user
            report.reviewed_at = timezone.now()
            report.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
            count += 1
        self.message_user(request, f"{count} user(s) banned.")

    @admin.action(description="Lift suspension for selected users' reports")
    def lift_suspension(self, request, queryset):
        count = 0
        for report in queryset:
            user = report.reported_user
            user.suspended_until = None
            user.is_banned = False
            user.save(update_fields=['suspended_until', 'is_banned'])
            count += 1
        self.message_user(request, f"Suspension/ban lifted for {count} user(s).")
