"""In-memory, per-client rate limiting (token bucket).

Each named bucket ("analyze", "jobs", ...) allows ``limit`` requests per ``window``
seconds with bursts up to ``limit``. State lives in this process, which matches the
single-process deployment model of the API; swap :class:`RateLimiter` for a Redis
implementation to scale horizontally.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds until one request is allowed again (0 when allowed)


class RateLimiter:
    def __init__(self, rules: dict[str, tuple[int, float]], *, enabled: bool = True, max_keys: int = 100_000) -> None:
        self._rules = dict(rules)
        self._enabled = enabled
        self._max_keys = max_keys
        self._state: dict[tuple[str, str], tuple[float, float]] = {}  # key -> (tokens, updated_at)
        self._lock = threading.Lock()

    def check(self, bucket: str, client: str, *, cost: float = 1.0, now: float | None = None) -> RateDecision:
        limit, window = self._rules[bucket]
        if not self._enabled:
            return RateDecision(True, limit, limit, 0)
        now = time.monotonic() if now is None else now
        rate = limit / window
        key = (bucket, client)
        with self._lock:
            tokens, updated = self._state.get(key, (float(limit), now))
            tokens = min(float(limit), tokens + max(0.0, now - updated) * rate)
            if tokens >= cost:
                tokens -= cost
                self._state[key] = (tokens, now)
                return RateDecision(True, limit, int(tokens), 0)
            self._state[key] = (tokens, now)
            if len(self._state) > self._max_keys:
                self._prune_locked(now)
            retry = math.ceil((cost - tokens) / rate)
            return RateDecision(False, limit, 0, max(1, retry))

    def prune(self, now: float | None = None) -> int:
        with self._lock:
            return self._prune_locked(time.monotonic() if now is None else now)

    def _prune_locked(self, now: float) -> int:
        """Drop buckets that have fully refilled; they carry no information."""
        stale = [
            key
            for key, (tokens, updated) in self._state.items()
            if tokens + (now - updated) * (self._rules[key[0]][0] / self._rules[key[0]][1]) >= self._rules[key[0]][0]
        ]
        for key in stale:
            del self._state[key]
        return len(stale)

    def __len__(self) -> int:
        return len(self._state)
