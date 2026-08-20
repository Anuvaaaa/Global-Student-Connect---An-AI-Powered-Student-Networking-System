# ai_agents/agents/translation_agent.py
from pydantic import BaseModel

from ai_agents.base import AIAgent


class TranslationResult(BaseModel):
    """
    Enforced response shape for the Translation agent. Passed to Gemini
    as a response_schema so translated_text is guaranteed present rather
    than hoping the model returns exactly the key the prompt asked for.
    """
    translated_text: str
    detected_source_language: str


class TranslationAgent(AIAgent):
    response_schema = TranslationResult

    # Routes onto the secondary Gemini API key/quota pool, separate from
    # Safety/Matching/Nudge on "primary" — translation calls happen far
    # more often (every unread message for every auto-translate user)
    # and would otherwise compete with those agents for the same quota.
    api_key_group = "secondary"

    # temperature=0 for the same reason MatchingAgent pins it: a
    # translation should not vary between identical calls. Without this,
    # re-opening the same conversation could show slightly different
    # wording for a message translated a moment ago.
    temperature = 0

    def build_prompt(self, payload: dict) -> str:
        return f"""Translate the following message into {payload['target_language']}.

Message: "{payload['text']}"

Preserve tone and meaning as closely as possible. Do not add commentary,
explanations, or quotation marks around the translation. If the message
is already in {payload['target_language']}, return it unchanged. Also
report the language you detected the original message was written in."""

    def parse_response(self, raw_text: str) -> dict:
        return self.parse_json(raw_text)
