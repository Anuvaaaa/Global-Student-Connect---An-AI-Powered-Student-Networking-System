from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),

    path('', include('accounts.urls')),
    path('', include('engagement.urls')),
    path('', include('social.urls')),      # placeholder — real one from Person B
    path('', include('matching.urls')),    # placeholder — real one from Person C
    path('', include('chat.urls')),        # placeholder — real one from Person C

    # moderation has no page of its own (per the brief) — nothing to include yet
    # path('', include('moderation.urls')),
]
