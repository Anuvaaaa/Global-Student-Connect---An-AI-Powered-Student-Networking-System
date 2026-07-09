from django.contrib import admin
from .models import University, User, Profile

@admin.register(University)
class UniversityAdmin(admin.ModelAdmin):
    list_display = ('domain', 'name')
    search_fields = ('domain', 'name')

admin.site.register(User)
admin.site.register(Profile)