# TARGET PATH: ai_agents/client.py
from google import genai
from google.genai import types
from django.conf import settings


class GeminiClient:
    """
    Singleton pattern used here: only one configured Gemini client exists
    for the whole app. Agents call GeminiClient.get_instance() instead of
    configuring their own connection.

    Retry/timeout tuning (added): the SDK's own defaults retry transient
    errors (timeouts, 429s, 5xx) up to 5 times with exponential backoff
    (1s, 2s, 4s, 8s, 16s...) before giving up — worst case 30+ seconds.
    That's exactly what produced the 24-27s hangs seen on flagged/
    quota-exhausted requests. Since safety_pipeline.py and
    nudge_service.py both already fail open on any exception, there's no
    benefit to retrying 5 times before falling back — every one of
    those seconds stalls a real user waiting on a fallback that was
    going to happen anyway. Cut to 2 attempts with a short timeout so
    failures surface fast and the fail-open path actually behaves like
    a fallback, not a 25-second delay before one.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options=types.HttpOptions(
                    timeout=12_000,  # milliseconds — API's own floor is 10s; kept some headroom above it
                    retry_options=types.HttpRetryOptions(
                        attempts=2,
                        initial_delay=1.0,
                        max_delay=4.0,
                        http_status_codes=[408, 429, 500, 502, 503, 504],
                    ),
                ),
            )
        return cls._instance

    @classmethod
    def get_instance(cls):
        return cls()

    def get_client(self):
        return self._client
