from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),

    path('', include('accounts.urls')),
    path('', include('engagement.urls')),

    # Uncomment each as Person B / Person C add their own urls.py —
    # doing it now would crash the server since those files don't exist yet.
    # path('', include('social.urls')),
    # path('', include('matching.urls')),
    # path('', include('chat.urls')),
    # path('', include('moderation.urls')),
]
