# TARGET PATH: ai_agents/urls.py — replace with this full version
# (adds the thread_history route alongside your existing ask_assistant one)
from django.urls import path

from . import views

app_name = "ai_agents"

urlpatterns = [
    path("assistant/ask/", views.ask_assistant, name="ask_assistant"),
    path("assistant/thread/<int:thread_id>/history/", views.thread_history, name="thread_history"),
]
