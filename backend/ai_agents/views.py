# TARGET PATH: ai_agents/views.py
"""
Platform Assistant endpoint. Thin wrapper around PlatformAssistantAgent.
Threads persist across page navigation, so the widget stays "in the same
conversation" as a student moves between pages, as long as the frontend
keeps passing the same thread_id back.

REQUIRES one small addition to ai_agents/models.py before this works:

    class AssistantMessage(models.Model):
        ...
        is_fallback = models.BooleanField(default=False)

This mirrors MessageTranslation.is_fallback — lets the frontend style a
"the assistant is napping" reply differently from a real answer, and lets
admins spot how often Gemini is actually failing. 
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET

from ai_agents.agents.platform_assistant_agent import get_fallback_message
from ai_agents.decorators import with_retry
from ai_agents.factory import AgentFactory
from ai_agents.models import AssistantMessage, AssistantThread
from ai_agents.agents.platform_assistant_agent import MAX_HISTORY_TURNS


def _get_or_create_thread(user, thread_id):
    """
    Reuses an existing thread if the frontend passed one back, otherwise
    starts a fresh thread for this user. A thread never belongs to more
    than one user, so a stale or foreign thread_id falls back to starting
    a new thread instead of ever attaching to someone else's history.
    """
    if thread_id:
        thread = AssistantThread.objects.filter(id=thread_id, user=user).first()
        if thread:
            return thread
    return AssistantThread.objects.create(user=user)


def _load_history(thread):
    """
    Maps AssistantMessage rows (role, text) into the generic
    {"role", "content"} shape the agent's format_history() expects, so the
    agent module stays independent of the exact ORM field name.
    """
    rows = thread.messages.order_by("created_at").values("role", "text")
    return [{"role": row["role"], "content": row["text"]} for row in rows]


@login_required
@require_POST
@with_retry(max_attempts=2)
def ask_assistant(request):
    question = request.POST.get("question", "").strip()
    thread_id = request.POST.get("thread_id")

    if not question:
        return JsonResponse({"error": "Question cannot be empty."}, status=400)

    thread = _get_or_create_thread(request.user, thread_id)
    history = _load_history(thread)

    agent = AgentFactory.get_agent("platform_assistant")

    try:
        result = agent.run({"question": question, "history": history})
        answer_text = result["answer"]
        in_scope = result["in_scope"]
        is_fallback = False
    except Exception:
        # Gemini unreachable or quota exhausted: casual apology instead of
        # a hard error. The student's question still gets saved so it
        # isn't lost when they retry.
        answer_text = get_fallback_message()
        in_scope = True
        is_fallback = True

    AssistantMessage.objects.create(thread=thread, role="user", text=question)
    AssistantMessage.objects.create(
        thread=thread,
        role="assistant",
        text=answer_text,
        is_fallback=is_fallback,
    )

    # last_message_at on AssistantThread is auto_now=True, but that only
    # updates on a save() of the AssistantThread row itself — creating
    # AssistantMessage rows above does not touch it. Touch it explicitly
    # so thread lists can sort by "most recently active."
    thread.save(update_fields=["last_message_at"])

    return JsonResponse({
        "thread_id": thread.id,
        "answer": answer_text,
        "in_scope": in_scope,
        "is_fallback": is_fallback,
    })
@login_required
@require_GET
def thread_history(request, thread_id):
    """
    Returns saved messages for a thread the requesting user actually owns,
    so the frontend can repopulate the visible chat log after a page
    refresh. Capped to MAX_HISTORY_TURNS — the same constant the agent
    itself uses to build Gemini's context — on purpose: showing more
    messages here than the assistant can actually see would look like a
    memory bug (bot "forgetting" something visibly still on screen),
    when older messages are still safely in the DB, just outside the
    model's context window for this reply.
    """
    thread = AssistantThread.objects.filter(id=thread_id, user=request.user).first()
    if not thread:
        return JsonResponse({"messages": []})
 
    rows = list(
        thread.messages.order_by("-created_at").values("role", "text")[:MAX_HISTORY_TURNS]
    )
    rows.reverse()  # back to chronological order for display
    return JsonResponse({"messages": rows})