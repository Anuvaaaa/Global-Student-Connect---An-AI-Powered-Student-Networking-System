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

    # Pinned to an explicit, stable (non-preview) model rather than the
    # "-latest" alias. The alias silently resolved to gemini-3.7-flash,
    # a preview model with only a 20 requests/day free-tier quota —
    # confirmed via `python list_models.py` against the real key, not
    # guessed. gemini-3.1-flash-lite is GA (not the "-preview" variant
    # also present in the model list), newer than the 2.5 generation
    # (which has a confirmed retirement date and community-reported
    # intermittent 404s), and the Lite tier historically carries a
    # meaningfully higher free daily quota than full Flash models.
    model_name = "gemini-3.1-flash-lite"

    # Optional: subclasses can set this to a Pydantic model to force
    # Gemini's structured output mode. Without this, the model is only
    # *asked* via prompt text to return certain JSON keys, and smaller/
    # cheaper models (like Flash-Lite) can silently drop fields it
    # decides are less important — this actually happened with
    # SafetyAgent's `severity`/`reasoning` fields. Setting response_schema
    # makes the API enforce the exact shape instead of hoping the model
    # complies.
    response_schema = None

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

        config = None
        if self.response_schema is not None:
            from google.genai import types
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=self.response_schema,
            )

        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )
        return self.parse_response(response.text)

    @staticmethod
    def parse_json(raw_text: str) -> dict:
        """Shared helper: Gemini sometimes wraps JSON in ```json fences."""
        cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)
