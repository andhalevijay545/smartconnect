"""Tiny in-memory rate limiter and login-failure tracker (pure Python).

Good enough for one server process (the project runs a single worker because
Socket.IO needs sticky connections).  For multiple workers use Redis instead.
"""
import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """Allow at most `limit` hits per `window` seconds for each key."""

    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float, now: float = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def clear(self):
        with self._lock:
            self._hits.clear()


class FailureTracker:
    """Lock a key (ip+username) for `lock_seconds` after `max_failures` failures."""

    def __init__(self):
        self._failures = defaultdict(list)
        self._locked_until = {}
        self._lock = threading.Lock()

    def locked_for(self, key: str, now: float = None) -> int:
        """Seconds still locked (0 if not locked)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            until = self._locked_until.get(key, 0)
            if until > now:
                return int(until - now) + 1
            self._locked_until.pop(key, None)
            return 0

    def failure(self, key: str, max_failures: int, lock_seconds: int, now: float = None) -> bool:
        """Record a failure. Returns True if this failure triggered a lock."""
        now = time.monotonic() if now is None else now
        with self._lock:
            recent = [t for t in self._failures[key] if t > now - lock_seconds]
            recent.append(now)
            self._failures[key] = recent
            if len(recent) >= max_failures:
                self._locked_until[key] = now + lock_seconds
                self._failures[key] = []
                return True
            return False

    def success(self, key: str):
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def clear(self):
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


register_limiter = SlidingWindowLimiter()
login_tracker = FailureTracker()
