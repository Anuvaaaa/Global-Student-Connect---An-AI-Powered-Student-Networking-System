# TARGET PATH: ai_agents/agents/matching_agent.py
from pydantic import BaseModel

from ai_agents.base import AIAgent


class MatchCompatibility(BaseModel):
    """
    Enforced response shape for the Matching agent. Passed to Gemini as a
    response_schema so both fields are guaranteed present, same reasoning
    as SafetyAssessment in safety_agent.py.

    score is deliberately typed as int (not float) — Gemini has no reason
    to reason in fractional percentage points here, and an int keeps the
    output easy to sanity-check against MIN_SCORE/MAX_SCORE in
    matching_service.py without a rounding step.
    """
    score: int
    reasoning: str


class MatchingAgent(AIAgent):
    response_schema = MatchCompatibility

    def build_prompt(self, payload: dict) -> str:
        a_interests = payload["user_a_interests"]
        b_interests = payload["user_b_interests"]
        a_country = payload["user_a_country"]
        b_country = payload["user_b_country"]

        shared = sorted(set(a_interests) & set(b_interests))

        return f"""You are scoring how compatible two international students would be as
friends on a university social platform, based on their interests and background.

Student A interests: {", ".join(a_interests) if a_interests else "none listed"}
Student B interests: {", ".join(b_interests) if b_interests else "none listed"}
Shared interests: {", ".join(shared) if shared else "none"}
Student A country: {a_country or "unknown"}
Student B country: {b_country or "unknown"}

Score their compatibility from 0 to 100, weighing shared interests most heavily,
with a small allowance for shared country/background. Give a brief reasoning a
student could read to understand the score."""

    def parse_response(self, raw_text: str) -> dict:
        return self.parse_json(raw_text)
