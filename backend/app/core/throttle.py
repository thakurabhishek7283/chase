"""A sliding-window limiter for the unauthenticated endpoints.

Scope, stated up front: **this is per-process, in memory.** Run several
workers and each keeps its own counters, so the effective ceiling is roughly
`workers x limit`. That is a real limitation and the reason this module is
small — it buys the order-of-magnitude reduction that turns online password
guessing from "feasible" into "not worth it", and when this app grows a Redis
it should move there rather than grow features here.

What it deliberately does *not* do is lock accounts by identity alone. A
limiter keyed only on the email address hands anyone a denial-of-service tool
against any account they can name; keying on the caller's address as well
means the victim of a spray is not locked out of their own account by it.
"""

import threading
import time
from collections import defaultdict, deque

from app.core.config import get_settings


class SlidingWindow:
    """Counts events per key over a moving window, with a lockout after the cap.

    Not async-aware and does not need to be: every operation is a few list
    mutations under a lock, with no await point where another task could
    interleave.
    """

    def __init__(self) -> None:
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str, *, window: int, limit: int) -> int:
        """Seconds the caller must wait, or 0 if the key is currently allowed.

        Read-only — checking must not itself consume budget, or a single
        request counting against two keys would charge twice for one attempt.
        """
        now = time.monotonic()
        with self._lock:
            blocked = self._blocked_until.get(key)
            if blocked is not None:
                if blocked > now:
                    return max(1, int(blocked - now))
                del self._blocked_until[key]
            events = self._events.get(key)
            if events is None:
                return 0
            self._evict(events, now - window)
            if len(events) < limit:
                return 0
            return max(1, int(events[0] + window - now))

    def register_failure(self, key: str, *, window: int, limit: int, lockout: int) -> None:
        """Record one failed attempt, tripping the lockout at the cap."""
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            self._evict(events, now - window)
            events.append(now)
            if len(events) >= limit:
                self._blocked_until[key] = now + lockout
                events.clear()

    def clear(self, key: str) -> None:
        """Forget a key — called on a *successful* sign-in.

        Without this, a user who mistypes a password a few times carries that
        history for the rest of the window and can be locked out by later
        typos that follow a success.
        """
        with self._lock:
            self._events.pop(key, None)
            self._blocked_until.pop(key, None)

    def reset(self) -> None:
        """Drop all state. For tests, and for nothing else."""
        with self._lock:
            self._events.clear()
            self._blocked_until.clear()

    @staticmethod
    def _evict(events: "deque[float]", cutoff: float) -> None:
        while events and events[0] < cutoff:
            events.popleft()


#: Separate limiters so registration pressure cannot lock out sign-in.
login_limiter = SlidingWindow()
register_limiter = SlidingWindow()


def reset_all() -> None:
    login_limiter.reset()
    register_limiter.reset()


def login_keys(ip: str | None, email: str | None) -> list[str]:
    """The keys one sign-in attempt is charged against.

    Both, not either: the IP key bounds one host spraying many accounts, the
    email key bounds a botnet converging on one account. Emails are folded so
    case variations cannot buy a fresh budget.
    """
    keys = []
    if ip:
        keys.append(f"ip:{ip}")
    if email:
        keys.append(f"email:{email.strip().lower()}")
    return keys


def throttle_enabled() -> bool:
    return get_settings().login_throttle_enabled
