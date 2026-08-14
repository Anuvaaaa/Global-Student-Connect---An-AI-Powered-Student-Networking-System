# ai_agents/client.py
from google import genai
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
            cls._instance._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return cls._instance

    @classmethod
    def get_instance(cls):
        return cls()

    def get_client(self):
        return self._client