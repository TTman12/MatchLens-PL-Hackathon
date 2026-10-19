"""Speeds and distances from the 10 Hz tracking frames."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import pairwise

from matchlens.contracts import FRAME_RATE_HZ, Frame

SPEED_WINDOW_FRAMES = FRAME_RATE_HZ // 2
"""Speeds are the peak of a 0.5 s rolling mean, as tracking providers report them."""


@dataclass(frozen=True)
class RunSummary:
    """One player's movement inside a time window."""

    player_id: str
    top_speed_kmh: float
    top_speed_t: float
    distance_m: float


class Tracking:
    """Time-indexed access to a match's frames, which must be sorted by ``t``."""

    def __init__(self, frames: list[Frame]) -> None:
        self.frames = frames
        self._times = [f.t for f in frames]

    def window(self, t0: float, t1: float) -> list[Frame]:
        """Frames with ``t0 <= t <= t1``."""
        lo = bisect_left(self._times, t0 - 1e-6)
        return self.frames[lo : bisect_right(self._times, t1 + 1e-6)]

    def run(self, player_id: str, t0: float, t1: float) -> RunSummary | None:
        return run_summary(self.window(t0, t1), player_id)

    def ball_speed_kmh(self, t: float, horizon_s: float = 0.3) -> float | None:
        """Ball speed just after ``t``, from frame positions. For when an event lacks one."""
        span = self.window(t, t + horizon_s)
        if len(span) < 2 or span[-1].t <= span[0].t:
            return None
        return round(math.dist(span[0].ball, span[-1].ball) / (span[-1].t - span[0].t) * 3.6, 1)


def run_summary(frames: list[Frame], player_id: str) -> RunSummary | None:
    """Top speed (and when it happened) and distance covered, or None if not on the pitch."""
    span = [f for f in frames if player_id in f.players]
    if len(span) < 2:
        return None
    speeds = [math.hypot(f.players[player_id][2], f.players[player_id][3]) * 3.6 for f in span]
    n = min(SPEED_WINDOW_FRAMES, len(speeds))
    rolling = [sum(speeds[i : i + n]) / n for i in range(len(speeds) - n + 1)]
    best = max(range(len(rolling)), key=rolling.__getitem__)
    peak_frame = span[best + n // 2] if best + n // 2 < len(span) else span[-1]
    distance = sum(
        math.dist(a.players[player_id][:2], b.players[player_id][:2]) for a, b in pairwise(span)
    )
    return RunSummary(
        player_id=player_id,
        top_speed_kmh=round(rolling[best], 1),
        top_speed_t=peak_frame.t,
        distance_m=round(distance, 1),
    )
