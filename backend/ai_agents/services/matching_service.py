# TARGET PATH: ai_agents/services/matching_service.py
"""
Fail-open pattern used here, same philosophy as safety_pipeline.py: the
AI Matching agent is an ENHANCEMENT over the existing plain-Python
compatibility formula (matching/utils.py -> compute_compatibility_score),
never a hard dependency the feature can't function without.

Matching must never stop working. If Gemini is unreachable, over quota,
times out, or returns a malformed/out-of-range score, this falls back to
the deterministic formula immediately — compute_compatibility_score is
left completely untouched so the fallback path is exactly the logic
that already shipped and was already trusted before any AI agent existed.

Not wrapped in a second retry loop here for the same reason noted in
safety_pipeline.py: the SDK (via GeminiClient) already retries transient
failures once with a short timeout. Stacking another retry on top would
just make a real user wait longer for a fallback that was going to
happen anyway.
"""
import logging

logger = logging.getLogger("ai_agents")

MIN_SCORE = 0
MAX_SCORE = 100


def get_compatibility_score(user_a, user_b):
    """
    Returns a float compatibility score for (user_a, user_b). Always
    returns a usable number — never raises — so callers never need their
    own try/except around this.
    """
    from matching.utils import compute_compatibility_score

    try:
        score = _get_ai_score(user_a, user_b)
        return float(score)
    except Exception as e:
        logger.error(f"Matching agent unavailable, falling back to rule-based scoring: {e}")
        return compute_compatibility_score(user_a, user_b)


def _get_ai_score(user_a, user_b):
    """
    Isolated so get_compatibility_score's try/except has one clear
    boundary: anything that goes wrong building the payload, calling
    Gemini, or validating its response lands here and triggers fallback.
    """
    from social.models import UserInterest
    from ai_agents.factory import AgentFactory

    a_interests = list(
        UserInterest.objects.filter(user=user_a).values_list("interest__name", flat=True)
    )
    b_interests = list(
        UserInterest.objects.filter(user=user_b).values_list("interest__name", flat=True)
    )
    profile_a = getattr(user_a, "profile", None)
    profile_b = getattr(user_b, "profile", None)

    agent = AgentFactory.get_agent("matching")
    result = agent.run({
        "user_a_interests": a_interests,
        "user_b_interests": b_interests,
        "user_a_country": getattr(profile_a, "country", None),
        "user_b_country": getattr(profile_b, "country", None),
    })

    score = result["score"]
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ValueError(f"Matching agent returned a non-numeric score: {score!r}")
    if not (MIN_SCORE <= score <= MAX_SCORE):
        raise ValueError(f"Matching agent returned an out-of-range score: {score!r}")

    return score
