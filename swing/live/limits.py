"""What keeps "Generate match" cheap: a daily budget of AI-explained matches and model calls, and a
per-visitor rate limit.

The budget is kept in a small JSON file (SWING_STATE_DIR) so a restart of the container keeps
the day's count while the file survives. It resets at midnight UTC. Past the budget, matches are
still generated and played, explained by the rules instead of the agents.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CALLS_PER_MATCH = 100  # what one match may take: ~65 for the cards, plus the recap and Spanish lines


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


class DailyBudget:
    """AI matches and model calls allowed per UTC day."""

    def __init__(self, path: Path | None, matches: int, calls: int, clock: Callable[[], str] = today) -> None:
        self.path = path
        self.max_matches = matches
        self.max_calls = calls
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"day": clock(), "matches": 0, "calls": 0}
        if path and path.exists():
            try:
                saved = json.loads(path.read_text())
                if saved.get("day") == self._state["day"]:
                    self._state.update({k: int(saved.get(k, 0)) for k in ("matches", "calls")})
            except (OSError, ValueError):
                pass  # a broken file only loses the count

    def _roll(self) -> None:
        if self._state["day"] != self._clock():
            self._state = {"day": self._clock(), "matches": 0, "calls": 0}

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._state))
        except OSError:
            pass

    def start_match(self) -> bool:
        """Take one AI match from today's budget, if there is room for a whole one."""
        with self._lock:
            self._roll()
            if self._state["matches"] >= self.max_matches or self._state["calls"] + CALLS_PER_MATCH > self.max_calls:
                return False
            self._state["matches"] += 1
            self._save()
            return True

    def add_calls(self, n: int) -> None:
        if n <= 0:
            return
        with self._lock:
            self._roll()
            self._state["calls"] += n
            self._save()

    def calls_left(self) -> int:
        with self._lock:
            self._roll()
            return max(0, self.max_calls - int(self._state["calls"]))

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            self._roll()
            s = self._state
            return {
                "ai_matches_left": max(0, self.max_matches - s["matches"]),
                "ai_matches_per_day": self.max_matches,
                "model_calls_left": max(0, self.max_calls - s["calls"]),
            }


class RateLimit:
    """At most `limit` requests per `window` seconds from each visitor."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: dict[str, deque[float]] = {}

    def allow(self, who: str) -> float:
        """0 if this request may go ahead (and counts it), else the seconds until one may."""
        now = self._clock()
        with self._lock:
            q = self._seen.setdefault(who, deque())
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return self.window - (now - q[0])
            q.append(now)
            if len(self._seen) > 10_000:  # forget the quiet ones
                for k in [k for k, v in self._seen.items() if not v or now - v[-1] >= self.window]:
                    del self._seen[k]
            return 0.0
