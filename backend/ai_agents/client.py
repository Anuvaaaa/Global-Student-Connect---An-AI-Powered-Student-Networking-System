# ai_agents/client.py
import google.generativeai as genai
from django.conf import settings


class GeminiClient:
    """
    Singleton pattern used here: only one configured Gemini client exists
    for the whole app. Agents call GeminiClient.get_instance() instead of
    configuring their own connection.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            genai.configure(api_key=settings.GEMINI_API_KEY)
            cls._instance._configured = True
        return cls._instance

    @classmethod
    def get_instance(cls):
        return cls()

    def get_model(self, model_name: str = "gemini-2.5-flash"):
        """Returns a GenerativeModel instance for the given model name."""
        return genai.GenerativeModel(model_name)
