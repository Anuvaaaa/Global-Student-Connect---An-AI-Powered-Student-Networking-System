from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),

    path('', include('accounts.urls')),          # login (root), setup/, profile/
    path('', include('engagement.urls')),         # notifications/
    path('', include('social.urls')),              # home feed — ⚠️ see note below

    path('connect/', include('matching.urls')),   # matching app — real
    path('chat/', include('chat.urls')),           # chat app — real
]
