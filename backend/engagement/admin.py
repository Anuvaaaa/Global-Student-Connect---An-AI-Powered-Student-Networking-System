from django.contrib import admin

from .models import (
    Badge,
    Mission,
    Notification,
    UserBadge,
    UserEngagement,
    UserMissionProgress,
)


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    # Ordered by badge_group/tier so the 3 rows per badge concept
    # (Bronze/Silver/Gold) sit together when you're seeding the ~15 rows.
    list_display = ('name', 'tier', 'badge_group', 'metric', 'threshold')
    list_filter = ('tier', 'metric')
    ordering = ('badge_group', 'tier')


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = ('name', 'frequency', 'target', 'linked_badge')
    list_filter = ('frequency',)


admin.site.register(Notification)
admin.site.register(UserEngagement)
admin.site.register(UserBadge)
admin.site.register(UserMissionProgress)
