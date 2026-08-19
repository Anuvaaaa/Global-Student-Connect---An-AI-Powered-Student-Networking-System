# TARGET PATH: ai_agents/client.py
from google import genai
from google.genai import types
from django.conf import settings


class GeminiClient:
    """
    Singleton pattern used here, keyed by API key group. Each key group
    ("primary", "secondary", etc.) gets its own configured client,
    created once and cached. Agents call GeminiClient.get_instance()
    instead of configuring their own connection. Calling with no
    argument defaults to "primary", so existing call sites that already
    call GeminiClient.get_instance() keep working unchanged.

    Retry/timeout: attempts=1, timeout=12_000ms. Every agent already
    fails open on any exception, so a single 12s attempt before falling
    back avoids stacking a second full timeout window on top of a call
    that's already failing. timeout stays above the API's 10s floor.
    """
    _instances = {}

    # Maps a key group name to the Django setting that holds its key.
    KEY_GROUP_SETTINGS = {
        "primary": "GEMINI_API_KEY",
        "secondary": "GEMINI_API_KEY_SECONDARY",
    }

    def __new__(cls, key_group="primary"):
        if key_group not in cls._instances:
            instance = super().__new__(cls)
            instance._client = genai.Client(
                api_key=cls._resolve_api_key(key_group),
                http_options=types.HttpOptions(
                    timeout=12_000,  # milliseconds — API floor is 10s, headroom kept above it
                    retry_options=types.HttpRetryOptions(
                        attempts=1,
                        http_status_codes=[408, 429, 500, 502, 503, 504],
                    ),
                ),
            )
            cls._instances[key_group] = instance
        return cls._instances[key_group]

    @classmethod
    def _resolve_api_key(cls, key_group):
        setting_name = cls.KEY_GROUP_SETTINGS.get(key_group)
        if setting_name is None:
            raise ValueError(f"Unknown Gemini API key group: {key_group!r}")
        return getattr(settings, setting_name)

    @classmethod
    def get_instance(cls, key_group="primary"):
        return cls(key_group)

    def get_client(self):
        return self._client
