from django.contrib import admin
from .models import Notification, UserEngagement, Badge, UserBadge, Mission, UserMissionProgress

admin.site.register(Notification)
admin.site.register(UserEngagement)
admin.site.register(Badge)
admin.site.register(UserBadge)
admin.site.register(Mission)
admin.site.register(UserMissionProgress)