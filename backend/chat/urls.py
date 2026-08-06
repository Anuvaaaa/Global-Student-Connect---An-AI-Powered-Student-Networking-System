from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.inbox_view, name='inbox'),
    path('poll/', views.inbox_poll_view, name='inbox_poll'),
    path('<int:conversation_id>/', views.conversation_view, name='conversation'),
    path('<int:conversation_id>/send/', views.send_message_view, name='send_message'),
    path('<int:conversation_id>/poll/', views.poll_messages_view, name='poll_messages'),
    path('<int:conversation_id>/end/', views.end_chat_view, name='end_chat'),
    path('<int:conversation_id>/leave/', views.leave_group_view, name='leave_group'),
    path(
        '<int:conversation_id>/message/<int:message_id>/translate/',
        views.translate_message_view,
        name='translate_message',
    ),
]
