# ai_agents/agents/verification_agent.py
from pydantic import BaseModel

from ai_agents.base import AIAgent


class UniversityNameSuggestion(BaseModel):
    """
    Enforced response shape (see AIAgent.response_schema), same reasoning
    as every other agent's schema — a single field here, since naming is
    this agent's only job.
    """
    university_name: str


class VerificationAgent(AIAgent):
    """
    Despite the name, this agent never decides whether an account is
    verified — that's is_academic_domain() in accounts/verification.py,
    a plain deterministic function that runs on every sign-in and never
    touches Gemini. This agent only runs once per NEW domain, after that
    domain has already passed the deterministic check, to guess the
    institution's real name (e.g. "buet.ac.bd" -> "Bangladesh University
    of Engineering and Technology") instead of leaving the raw domain
    text as the display name. A wrong or ugly guess here is fixed later
    in Django admin — it never blocks sign-up, and never re-runs once a
    University row exists for that domain.

    Runs on the secondary API key, same pool as Translation, since
    Safety/Matching/Nudge already share primary and this is a separate,
    infrequent workload (once per new domain, not once per request).
    """
    response_schema = UniversityNameSuggestion
    api_key_group = "secondary"

    # Pinned for the same reason MatchingAgent/TranslationAgent pin it —
    # the same domain should always resolve to the same guessed name,
    # not a different phrasing each time a brand-new domain shows up.
    temperature = 0

    def build_prompt(self, payload: dict) -> str:
        domain = payload["domain"]
        return f"""A student is signing up on a university networking platform using an
email address ending in "{domain}". This domain belongs to a real academic
institution.

Identify the most likely full, real name of this institution in English
(e.g. "buet.ac.bd" -> "Bangladesh University of Engineering and Technology",
"monash.edu.au" -> "Monash University").

If you cannot confidently identify a specific institution from this domain,
give your best short guess based on the domain text itself rather than
leaving the name blank."""

    def parse_response(self, raw_text: str) -> dict:
        return self.parse_json(raw_text)
