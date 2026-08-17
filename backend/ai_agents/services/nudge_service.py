# TARGET PATH: ai_agents/services/nudge_service.py
"""
Generates an encouraging nudge message via the Nudge agent when a
user's badge/mission progress crosses NUDGE_THRESHOLD_PCT (see
engagement/utils.py), and logs it as a NudgeLog + Notification.

Same separation of concerns as the Safety pipeline: the agent
(ai_agents/agents/nudge_agent.py) only produces message text. All
deterministic gating — the closeness threshold, and the rate-limit
logic below — lives in plain Python outside the agent, never inside
a prompt.

Rate-limiting: delta-based, not time-based. We don't re-nudge for the
same badge/mission unless progress has moved at least
MIN_PROGRESS_DELTA_PCT points past the last nudge sent for it. A fixed
time cooldown would either spam a fast-progressing user with repeats
at the same 70% before they've moved, or leave a stalled user
unprompted for too long — comparing against actual progress movement
scales to how the user is behaving instead of the clock.

Fail-open on Gemini failure, matching the Safety pipeline's behavior:
if the Nudge agent is unreachable (quota exhausted, API down), we
skip silently rather than raising into the signal receiver — a signal
receiver raising would propagate back into whatever action triggered
it (e.g. check_and_award_badges() being called after a message send),
and a missed nudge should never be able to break an unrelated action.
"""
import logging

logger = logging.getLogger("ai_agents")

MIN_PROGRESS_DELTA_PCT = 15


def _last_nudge_for(user, *, badge=None, mission=None):
    from ai_agents.models import NudgeLog

    qs = NudgeLog.objects.filter(user=user)
    qs = qs.filter(badge=badge) if badge else qs.filter(mission=mission)
    return qs.order_by("-sent_at").first()


def generate_nudge(user, progress_pct, *, badge=None, mission=None):
    """
    Call from a signal receiver (engagement/signals.py) once
    progress_pct has already crossed the "close" threshold. Exactly
    one of badge/mission must be provided.

    Returns the created NudgeLog, or None if skipped (rate-limited or
    the Nudge agent was unreachable). Callers should treat None as a
    normal, expected outcome — not an error.
    """
    if bool(badge) == bool(mission):
        raise ValueError("generate_nudge requires exactly one of badge or mission")

    last_nudge = _last_nudge_for(user, badge=badge, mission=mission)
    if last_nudge and (progress_pct - last_nudge.progress_pct) < MIN_PROGRESS_DELTA_PCT:
        return None

    try:
        from ai_agents.factory import AgentFactory
        agent = AgentFactory.get_agent("nudge")
        result = agent.run({
            "progress_pct": progress_pct,
            "badge_name": badge.name if badge else None,
            "mission_name": mission.name if mission else None,
        })
        message_text = result["nudge_text"]
    except Exception as e:
        logger.error(f"Nudge agent unavailable, skipping nudge: {e}")
        return None

    from ai_agents.models import NudgeLog

    nudge_log = NudgeLog.objects.create(
        user=user,
        nudge_type="badge_progress" if badge else "mission_progress",
        badge=badge,
        mission=mission,
        progress_pct=progress_pct,
        message_text=message_text,
    )

    from engagement.models import Notification

    Notification.objects.create(
        user=user,
        type="badge" if badge else "mission",
        title="Almost there! 🎯",
        description=nudge_log.message_text,
        cta_label="View Progress",
        cta_href="/profile/",
    )

    return nudge_log
