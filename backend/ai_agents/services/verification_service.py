# ai_agents/services/verification_service.py
"""
Create-then-upgrade pattern, distinct from the fail-open pattern used in
matching_service.py/translation_pipeline.py. Those wrap an AI call and
fall back to a deterministic result on failure. This does the opposite
order: the University row is created SYNCHRONOUSLY with a deterministic
name first (domain.split('.')[0]), so a new sign-up is never waiting on
Gemini at all — then, only for a genuinely new domain, an attempt is
made to upgrade that name via the Verification agent. If the agent call
fails, the row already has a usable fallback name and nothing further
happens; no retry queue, no blocked account creation.

This only ever runs once per domain — every student after the first
from the same domain hits the already-existing University row and never
reaches this module at all (see accounts/verification.py).
"""
import logging

logger = logging.getLogger("ai_agents")


def resolve_university(domain):
    """
    Returns the University row for this domain, creating it if this is
    the first student ever seen from it. Never raises — a Gemini failure
    just means the row keeps its deterministic fallback name.
    """
    from accounts.models import University

    university, created = University.objects.get_or_create(
        domain=domain,
        defaults={"name": _fallback_name(domain)},
    )

    if not created:
        return university

    try:
        ai_name = _get_ai_name(domain)
        university.name = ai_name
        university.save(update_fields=["name"])
    except Exception as e:
        logger.error(
            f"Verification agent unavailable, keeping fallback name for "
            f"{domain!r}: {e}"
        )

    return university


def _fallback_name(domain):
    """
    Deterministic guess used both as the initial name on creation and as
    the permanent name if the agent never succeeds. Admin cleans this up
    manually in Django admin — see the project's Section 3 plan.
    """
    return domain.split(".")[0]


def _get_ai_name(domain):
    """
    Isolated so resolve_university's try/except has one clear boundary:
    anything that goes wrong calling Gemini or validating its response
    lands here.
    """
    from ai_agents.factory import AgentFactory

    agent = AgentFactory.get_agent("verification")
    result = agent.run({"domain": domain})

    name = result.get("university_name")
    if not name or not isinstance(name, str):
        raise ValueError(f"Verification agent returned an invalid name: {name!r}")

    return name.strip()
