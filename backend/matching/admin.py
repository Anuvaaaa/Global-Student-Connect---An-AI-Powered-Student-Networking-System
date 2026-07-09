from django.contrib import admin
from .models import MatchRequest, Connection, Block, StudentGroup, GroupMember

admin.site.register(MatchRequest)
admin.site.register(Connection)
admin.site.register(Block)
admin.site.register(StudentGroup)
admin.site.register(GroupMember)