# ai_agents/agents/safety_agent.py
from enum import Enum

from pydantic import BaseModel

from ai_agents.base import AIAgent


class SafetyCategory(str, Enum):
    HARASSMENT = "harassment"
    SPAM = "spam"
    INAPPROPRIATE_CONTENT = "inappropriate_content"
    OTHER = "other"


class SafetySeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SafetyAssessment(BaseModel):
    """
    Enforced response shape for the Safety agent. Passed to Gemini as a
    response_schema so all five fields are guaranteed present — relying
    on prompt text alone let the model silently drop severity/reasoning.
    """
    flagged: bool
    category: SafetyCategory
    severity: SafetySeverity
    confidence: float
    reasoning: str


class SafetyAgent(AIAgent):
    response_schema = SafetyAssessment

    def build_prompt(self, payload: dict) -> str:
        return f"""You are assessing this message for harassment, grooming, or policy
violations on a university student platform. Message: "{payload['text']}"

Assess flagged status, category, severity, your confidence (0-1), and a brief
reasoning a human moderator could read to understand your assessment."""

    def parse_response(self, raw_text: str) -> dict:
        return self.parse_json(raw_text)
