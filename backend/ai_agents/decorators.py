# ai_agents/decorators.py
import time
import logging
from functools import wraps

logger = logging.getLogger("ai_agents")


def with_retry(max_attempts=3, delay_seconds=1):
    """
    Decorator pattern used here: adds retry + logging behavior around
    any agent call, independent of what the agent actually does.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    logger.warning(f"Agent call failed (attempt {attempt}): {e}")
                    time.sleep(delay_seconds * attempt)
            logger.error(f"Agent call failed after {max_attempts} attempts: {last_error}")
            raise last_error
        return wrapper
    return decorator
