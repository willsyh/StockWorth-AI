"""Small in-memory sliding-window rate limiter (per process).

Good enough for a single-instance MVP. Use a shared store (e.g. Redis) when
running several backend instances.
"""

import threading
import time
from collections import defaultdict, deque

from app.core.errors import AppError


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = int(self.window - (now - hits[0])) + 1
                raise AppError(
                    429,
                    "rate_limited",
                    f"Terlalu banyak permintaan. Coba lagi dalam {retry} detik.",
                    {"retry_after_seconds": retry},
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
