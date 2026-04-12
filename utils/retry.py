import asyncio
import random
from functools import wraps
from utils.logger import log


def async_retry(max_attempts: int = 5, base_delay: float = 1.0, max_delay: float = 60.0):
    """Retry decorator with exponential backoff + jitter for async functions."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt == max_attempts:
                        log.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    delay += random.uniform(0, delay * 0.1)
                    log.warning(f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. Retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)
            raise last_exc

        return wrapper

    return decorator
