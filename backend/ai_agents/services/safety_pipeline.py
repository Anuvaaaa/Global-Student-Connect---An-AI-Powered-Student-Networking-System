# ai_agents/services/safety_pipeline.py
"""
Chain of Responsibility pattern used here: a message passes through
the LLM Safety agent, which decides whether it's allowed through,
queued for human review, or blocked outright.

Note on retries: google-genai's client already retries transient
failures internally (visible as `tenacity` in its tracebacks). We do
NOT wrap it in a second retry loop here — stacking our own retries on
top of the SDK's already-retrying call compounds wait times badly.

Fail-open on Gemini failure: if the Safety agent can't be reached at
all (quota exhausted, API down, etc.), the message is still allowed
through rather than the whole send silently hanging or crashing.

Auto-block gate uses `severity`, not `confidence`. `confidence` measures
how sure Gemini is about its own flagged/not-flagged call — a model can
be 95% confident something ISN'T harassment just as easily as 95%
confident it IS, so it doesn't measure how bad a flagged message is.
`severity` is what actually classifies how serious a violation is
(low/medium/high), so it's the right field to gate auto-block on.
"""
import logging

logger = logging.getLogger("ai_agents")

# Only this severity level is blocked outright before ever reaching the
# recipient. Anything flagged but less severe still sends, and gets
# queued as a SafetyFlag for a human to review.
AUTO_BLOCK_SEVERITIES = {"high"}


def check_message(text: str) -> dict:
    try:
        from ai_agents.factory import AgentFactory
        agent = AgentFactory.get_agent("safety")
        llm_result = agent.run({"text": text})
    except Exception as e:
        logger.error(f"Safety agent unavailable, allowing message through unscreened: {e}")
        return {"action": "allow", "stage": "error_fallback"}

    if llm_result["flagged"]:
        if llm_result.get("severity") in AUTO_BLOCK_SEVERITIES:
            return {"action": "auto_block", "stage": "llm", **llm_result}
        return {"action": "queue_human_review", "stage": "llm", **llm_result}

    return {"action": "allow", "stage": "clear"}
