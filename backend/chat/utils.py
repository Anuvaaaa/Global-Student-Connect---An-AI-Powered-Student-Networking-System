"""
chat/utils.py
"""

import datetime

from django.utils import timezone

from .models import MessageTranslation
from ai_agents.services.translation_pipeline import translate_text
from engagement.models import UserEngagement
from engagement.utils import record_mission_progress


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

    Retry-on-view: if the cached row was itself a fallback (is_fallback
    True — the original attempt hit the circuit breaker or a Gemini
    error), this re-attempts translation on every subsequent call rather
    than trusting the stale passthrough forever. Once a real translation
    succeeds, is_fallback flips to False and it's cached for good, same
    as any other row. A row that's already a real translation is never
    re-sent to Gemini.

    The returned MessageTranslation also gets a runtime-only
    `used_fallback` attribute (never persisted separately — mirrors
    is_fallback) so callers that only care about the current call's
    outcome, not the stored flag, can check it the same way as before.
    """
    if not target_language:
        return None

    existing = MessageTranslation.objects.filter(
        message=message, language=target_language
    ).first()

    if existing is not None and not existing.is_fallback:
        existing.used_fallback = False
        return existing

    result = translate_text(message.text, target_language)
    is_fallback = (result['stage'] == 'error_fallback')

    if existing is not None:
        # retrying a previously-failed row
        if not is_fallback:
            existing.translated_text = result['translated_text']
            existing.is_fallback = False
            existing.save()
        existing.used_fallback = is_fallback
        return existing

    translation = MessageTranslation.objects.create(
        message=message,
        language=target_language,
        translated_text=result['translated_text'],
        is_fallback=is_fallback,
    )
    translation.used_fallback = is_fallback

    if for_user is not None:
        eng, _ = UserEngagement.objects.get_or_create(user=for_user)
        eng.translations_used += 1
        eng.save()
        record_mission_progress(for_user, 'use_translation_5x')

    return translation


def date_label_for(dt):
    """
    Turns a datetime into 'Today' / 'Yesterday' / 'August 08, 2026' —
    used to build real day-by-day date separators in the message list.
    """
    now_local = timezone.localtime(timezone.now())
    dt_local = timezone.localtime(dt)
    today = now_local.date()
    d = dt_local.date()

    if d == today:
        return 'Today'
    if d == today - datetime.timedelta(days=1):
        return 'Yesterday'
    return dt_local.strftime('%B %d, %Y')


# =====================================================================
# Short country codes — replaces the generic 🌍 placeholder used
# everywhere a per-student avatar/flag was needed. Matches the exact
# 25-country list from profile-setup.html. Not strict ISO 3166 (UK
# instead of GB) — chosen for readability over standards-compliance,
# since this is cosmetic, not used for any lookup/matching logic.
# =====================================================================
COUNTRY_CODES = {
    'Bangladesh': 'BD',
    'India': 'IN',
    'Pakistan': 'PK',
    'Sri Lanka': 'LK',
    'Nepal': 'NP',
    'Malaysia': 'MY',
    'Indonesia': 'ID',
    'Philippines': 'PH',
    'Japan': 'JP',
    'South Korea': 'KR',
    'China': 'CN',
    'Saudi Arabia': 'SA',
    'United Arab Emirates': 'AE',
    'Turkey': 'TR',
    'Nigeria': 'NG',
    'Ghana': 'GH',
    'Kenya': 'KE',
    'Brazil': 'BR',
    'Mexico': 'MX',
    'United Kingdom': 'UK',
    'Germany': 'DE',
    'France': 'FR',
    'United States': 'US',
    'Canada': 'CA',
    'Australia': 'AU',
}


def country_code_for(country_name):
    """
    Returns a short 2-letter-ish code for display. Falls back to the
    first two letters of whatever string is stored if it's somehow not
    in the fixed list (shouldn't happen — Profile.country is a choice
    field — but better than crashing on unexpected data).
    """
    if not country_name:
        return '—'
    return COUNTRY_CODES.get(country_name, country_name[:2].upper())
