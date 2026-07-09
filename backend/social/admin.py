from django.contrib import admin
from .models import Interest, UserInterest, Post, Like, Comment

admin.site.register(Interest)
admin.site.register(UserInterest)
admin.site.register(Post)
admin.site.register(Like)
admin.site.register(Comment)