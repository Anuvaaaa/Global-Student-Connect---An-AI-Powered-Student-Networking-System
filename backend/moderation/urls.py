from django.urls import path
from . import views

app_name = 'moderation'

urlpatterns = [
    path('report/<int:conversation_id>/', views.report_user_view, name='report_user'),
]
