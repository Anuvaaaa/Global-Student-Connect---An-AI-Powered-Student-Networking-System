"""
chat/utils.py

STUB translation logic — per the deferred-AI-agents decision, this just
echoes the original text for now. The MessageTranslation table and every
caller of this function already work end-to-end, so swapping in a real
Translation Agent API call later only means changing what happens
inside this one function.
"""

from .models import MessageTranslation
from engagement.models import UserEngagement


def translate_message(message, target_language, for_user=None):
    """
    Get-or-create a MessageTranslation row for (message, target_language).
    Idempotent — calling this twice for the same message+language does
    NOT create a duplicate row or double-count usage.

    for_user: if given, and this is the FIRST time this translation was
    computed (not just re-fetched), increments that user's
    UserEngagement.translations_used. Only counts real "first-time"
    translation work, not every re-render of an already-translated
    message.
    """
    if not target_language:
        return None

    translation, created = MessageTranslation.objects.get_or_create(
        message=message,
        language=target_language,
        defaults={'translated_text': message.text},  # stub: passthrough
    )

    if created and for_user is not None:
        eng, _ = UserEngagement.objects.get_or_create(user=for_user)
        eng.translations_used += 1
        eng.save()

    return translation
