# TARGET PATH: ai_agents/urls.py — replace with this full version
# Root urls.py already adds the "assistant/" prefix via
# path('assistant/', include('ai_agents.urls')), so these paths no longer
# repeat it themselves — final resolved URLs are /assistant/ask/ and
# /assistant/thread/<id>/history/, not /assistant/assistant/...
from django.urls import path

from . import views

app_name = "ai_agents"

urlpatterns = [
    path("ask/", views.ask_assistant, name="ask_assistant"),
    path("thread/<int:thread_id>/history/", views.thread_history, name="thread_history"),
]
