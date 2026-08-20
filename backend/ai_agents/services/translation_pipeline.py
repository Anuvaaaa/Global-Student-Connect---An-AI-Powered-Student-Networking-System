# ai_agents/services/translation_pipeline.py
"""
Fail-open wrapper around TranslationAgent. Mirrors safety_pipeline.py's
role for the Safety agent: callers never touch AgentFactory or Gemini
directly, and a failure here never blocks a send/receive/poll — it just
falls back to the original text.

Circuit breaker: after FAILURE_THRESHOLD consecutive failures, the
breaker opens and every call short-circuits straight to fallback
(skipping the Gemini call entirely) for BREAKER_COOLDOWN_SECONDS. This
matters more for translation than it did for Safety, because translation
runs on every unread message for every auto-translate user on every
poll — without a breaker, one Gemini outage would mean every single
poll request still pays the full timeout before falling back.
"""
import logging

from django.core.cache import cache

logger = logging.getLogger("ai_agents")

FAILURE_COUNT_KEY = "translation_agent:consecutive_failures"
BREAKER_OPEN_KEY = "translation_agent:breaker_open"
FAILURE_THRESHOLD = 3
BREAKER_COOLDOWN_SECONDS = 120

NAPPING_NOTICE = (
    "Heads up: our translation agent is taking a quick nap 😴 — showing "
    "the original text for now."
)


def _breaker_is_open() -> bool:
    return bool(cache.get(BREAKER_OPEN_KEY, False))


def _record_failure() -> None:
    cache.add(FAILURE_COUNT_KEY, 0)
    count = cache.incr(FAILURE_COUNT_KEY)
    if count >= FAILURE_THRESHOLD:
        cache.set(BREAKER_OPEN_KEY, True, timeout=BREAKER_COOLDOWN_SECONDS)
        cache.delete(FAILURE_COUNT_KEY)
        logger.warning(
            f"Translation agent circuit breaker OPEN for {BREAKER_COOLDOWN_SECONDS}s "
            f"after {count} consecutive failures"
        )


def _reset_failures() -> None:
    cache.delete(FAILURE_COUNT_KEY)


def translate_text(text: str, target_language: str) -> dict:
    """
    Returns {'translated_text': str, 'stage': 'success' | 'error_fallback' | 'skipped'}.
    Never raises — every failure path (breaker open, API error, malformed
    response) falls back to returning the original text unchanged.
    """
    if not text or not target_language:
        return {'translated_text': text, 'stage': 'skipped'}

    if _breaker_is_open():
        return {'translated_text': text, 'stage': 'error_fallback'}

    from ai_agents.factory import AgentFactory
    try:
        agent = AgentFactory.get_agent("translation")
        result = agent.run({'text': text, 'target_language': target_language})
        translated = result.get('translated_text')
        if not translated:
            raise ValueError("Translation agent returned an empty translated_text")
        _reset_failures()
        return {'translated_text': translated, 'stage': 'success'}
    except Exception as e:
        logger.warning(f"Translation agent call failed, falling back to original text: {e}")
        _record_failure()
        return {'translated_text': text, 'stage': 'error_fallback'}
