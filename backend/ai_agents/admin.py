from django.contrib import admin
from .models import SafetyFlag, NudgeLog, AssistantThread, AssistantMessage


@admin.register(SafetyFlag)
class SafetyFlagAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "severity", "category", "status", "report", "created_at")
    list_filter = ("severity", "category", "status")
    search_fields = ("ai_reasoning",)
    readonly_fields = ("created_at",)


@admin.register(NudgeLog)
class NudgeLogAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "nudge_type", "sent_at", "was_dismissed")
    list_filter = ("nudge_type", "was_dismissed")
    search_fields = ("user__email", "message_text")
    readonly_fields = ("sent_at",)


@admin.register(AssistantThread)
class AssistantThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "created_at", "last_message_at")
    search_fields = ("user__email", "title")
    readonly_fields = ("created_at", "last_message_at")


@admin.register(AssistantMessage)
class AssistantMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("text",)
    readonly_fields = ("created_at",)
