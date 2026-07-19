from django.urls import path

from . import views

app_name = 'engagement'

urlpatterns = [
    path('notifications/', views.notifications_view, name='notifications'),
    path('notifications/<int:notification_id>/read/', views.mark_notification_read_view, name='mark_read'),
    path('notifications/mark-all-read/', views.mark_all_read_view, name='mark_all_read'),
]
