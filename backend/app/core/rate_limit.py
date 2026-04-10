from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from .exceptions import RateLimitError


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def enforce(self, *, bucket: str, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        composite_key = f"{bucket}:{key}"
        with self._lock:
            events = self._events[composite_key]
            cutoff = now - window_seconds
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= limit:
                raise RateLimitError(
                    f"Demasiados intentos recientes para '{bucket}'. Espera un momento y vuelve a intentar.",
                )
            events.append(now)


rate_limiter = InMemoryRateLimiter()
