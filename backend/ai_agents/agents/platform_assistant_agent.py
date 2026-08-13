# ai_agents/agents/platform_assistant_agent.py
"""
STUB: replace with the real implementation from
GSC_AI_INTEGRATION_PLAN.md section 2 (PlatformAssistant Agent).
Kept minimal here only so factory.py has something concrete to import
while the shared architecture is being wired up.
"""
from ai_agents.base import AIAgent


class PlatformAssistantAgent(AIAgent):
    def build_prompt(self, payload: dict) -> str:
        raise NotImplementedError("PlatformAssistantAgent.build_prompt not implemented yet")

    def parse_response(self, raw_text: str) -> dict:
        return self.parse_json(raw_text)
