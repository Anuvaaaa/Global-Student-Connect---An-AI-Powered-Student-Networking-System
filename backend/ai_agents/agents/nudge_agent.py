# TARGET PATH: ai_agents/agents/nudge_agent.py
from pydantic import BaseModel, Field

from ai_agents.base import AIAgent


class NudgeMessage(BaseModel):
    """
    Enforced response shape (see AIAgent.response_schema). Kept to a
    single field deliberately — this agent has exactly one job, unlike
    SafetyAssessment's five fields, so there's nothing else to enforce.
    """
    nudge_text: str = Field(
        description="A short, warm, encouraging nudge message, max 20 words."
    )


class NudgeAgent(AIAgent):
    """
    Generates the WORDING of an encouraging nudge when a user is close
    to completing a badge or mission. This agent never decides WHETHER
    to nudge, how close is "close enough," or how often to re-nudge —
    all of that is deterministic logic in engagement/utils.py
    (NUDGE_THRESHOLD_PCT) and ai_agents/services/nudge_service.py
    (rate-limiting). Gemini's only input here is one number and one
    name; its only output is one sentence.
    """

    response_schema = NudgeMessage

    def build_prompt(self, payload: dict) -> str:
        badge_name = payload.get("badge_name")
        mission_name = payload.get("mission_name")

        if badge_name:
            target_kind, target_name = "badge", badge_name
        elif mission_name:
            target_kind, target_name = "mission", mission_name
        else:
            raise ValueError("NudgeAgent payload requires badge_name or mission_name")

        return (
            f"A university student on a student-networking platform is "
            f"{payload['progress_pct']}% of the way toward the {target_kind} "
            f'"{target_name}". Write one short, warm, encouraging nudge '
            f"message (max 20 words) motivating them to finish it. Address "
            f'them directly as "you", not by name. Use at most one '
            f"exclamation mark.\n\n"
            f'Respond ONLY with JSON, no markdown fences:\n'
            f'{{"nudge_text": "..."}}'
        )

    def parse_response(self, raw_text: str) -> dict:
        return self.parse_json(raw_text)
