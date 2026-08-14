# ai_agents/base.py
import json
from abc import ABC, abstractmethod


class AIAgent(ABC):
    """
    Strategy pattern used here: each concrete agent (Verification,
    Matching, Translation, Safety, Nudge) implements this same interface.
    Callers depend on AIAgent, never on a specific agent class, so agents
    can be swapped or added without touching calling code.
    """

    # Override per agent: use the cheaper/faster model unless the task
    # needs more judgment (see per-agent notes in section 2).
    model_name = "gemini-flash-latest"

    @abstractmethod
    def build_prompt(self, payload: dict) -> str:
        """Turn input data into the prompt string sent to Gemini."""
        ...

    @abstractmethod
    def parse_response(self, raw_text: str) -> dict:
        """Turn Gemini's raw text output into a structured dict."""
        ...

    def run(self, payload: dict) -> dict:
        """
        Template Method pattern used here: run() defines the fixed
        skeleton (build prompt -> call API -> parse) that is the same
        for every agent. Subclasses only override build_prompt() and
        parse_response(), never run() itself.
        """
        from ai_agents.client import GeminiClient
        client = GeminiClient.get_instance().get_client()
        prompt = self.build_prompt(payload)
        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )
        return self.parse_response(response.text)

    @staticmethod
    def parse_json(raw_text: str) -> dict:
        """Shared helper: Gemini sometimes wraps JSON in ```json fences."""
        cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)
