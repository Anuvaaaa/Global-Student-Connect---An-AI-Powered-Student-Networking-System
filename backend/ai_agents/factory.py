# ai_agents/factory.py
from ai_agents.agents.verification_agent import VerificationAgent
from ai_agents.agents.matching_agent import MatchingAgent
from ai_agents.agents.translation_agent import TranslationAgent
from ai_agents.agents.safety_agent import SafetyAgent
from ai_agents.agents.nudge_agent import NudgeAgent
from ai_agents.agents.platform_assistant_agent import PlatformAssistantAgent


class AgentFactory:
    """
    Factory pattern used here: centralizes agent construction so
    callers never import or instantiate agent classes directly.
    Usage: agent = AgentFactory.get_agent("safety")
    """
    _registry = {
        "verification": VerificationAgent,
        "matching": MatchingAgent,
        "translation": TranslationAgent,
        "safety": SafetyAgent,
        "nudge": NudgeAgent,
        "platform_assistant": PlatformAssistantAgent,
    }

    @classmethod
    def get_agent(cls, name: str):
        agent_cls = cls._registry.get(name)
        if agent_cls is None:
            raise ValueError(f"Unknown agent: {name}")
        return agent_cls()
