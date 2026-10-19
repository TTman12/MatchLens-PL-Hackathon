"""Per-event metrics: pass difficulty, pressure, line breaks, xG and shot speed.

The simulator writes most of these into event ``qualifiers``. When one is missing (a
hand-made match, or a real feed through the adapter), it is computed here from the event
and the tracking frames, so every later stage can rely on it being present.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from matchlens.contracts import PITCH_LENGTH_M, PITCH_WIDTH_M, EventType, MatchEvent
from matchlens.contracts.pitch import Direction, attacking_direction, to_attacking

from .data import MatchData
from .tracking import Tracking

PRESSURE_RADIUS_M = 5.0
"""An opponent this close or closer counts as pressure; at 0 m pressure is 1."""

PASS_TYPE_DIFFICULTY = {"through": 0.1, "cross": 0.08, "long": 0.08, "lofted": 0.05}

GOAL_CENTRE = (PITCH_LENGTH_M, PITCH_WIDTH_M / 2)
GOAL_HALF_WIDTH_M = 3.66


@dataclass(frozen=True)
class PassQuality:
    distance_m: float
    difficulty: float
    pressure_on_passer: float
    line_breaking: bool
    forward_m: float


@dataclass(frozen=True)
class ShotQuality:
    xg: float
    distance_m: float
    shot_speed_kmh: float | None


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


class EventMetrics:
    """Fills in missing per-event metrics from the event and the frames."""

    def __init__(self, match: MatchData, tracking: Tracking | None = None) -> None:
        self.match = match
        self.tracking = tracking or Tracking(match.frames)

    def direction(self, team_id: str, period: int) -> Direction:
        return attacking_direction(
            self.match.meta.home_attacks_in_period_1, self.match.is_home(team_id), period
        )

    def opponents_at(self, event: MatchEvent) -> list[tuple[float, float]]:
        """Opponent positions at the event, in the acting team's attacking frame."""
        assert event.team_id is not None
        frames = self.tracking.window(event.t - 0.05, event.t + 0.05)
        if not frames:
            return []
        rival = self.match.opponent(event.team_id)
        direction = self.direction(event.team_id, event.period)
        return [
            to_attacking((state[0], state[1]), direction)
            for pid, state in frames[0].players.items()
            if pid.startswith(f"{rival}-")
        ]

    def pressure(self, event: MatchEvent) -> float:
        """0 to 1: how closely the nearest opponent is marking the player on the ball."""
        if event.start is None:
            return 0.0
        start = event.start
        nearest = min(
            (math.dist(start, p) for p in self.opponents_at(event)), default=PRESSURE_RADIUS_M
        )
        return round(clamp(1 - nearest / PRESSURE_RADIUS_M), 2)

    def pass_quality(self, event: MatchEvent) -> PassQuality | None:
        """Distance, difficulty, pressure and line break for a pass or set-piece delivery."""
        if event.start is None or event.end is None:
            return None
        q = event.qualifiers
        distance = q.distance_m if q.distance_m is not None else math.dist(event.start, event.end)
        forward = event.end[0] - event.start[0]
        pressure = (
            q.pressure_on_passer if q.pressure_on_passer is not None else self.pressure(event)
        )
        if q.line_breaking is not None:
            line_breaking = q.line_breaking
        else:
            lo, hi = sorted((event.start[0], event.end[0]))
            bypassed = sum(1 for x, _ in self.opponents_at(event) if lo < x < hi)
            line_breaking = forward >= 10 and bypassed >= 2
        if q.difficulty is not None:
            difficulty = q.difficulty
        else:
            difficulty = clamp(
                0.12
                + 0.011 * min(distance, 45)
                + 0.25 * pressure
                + (0.15 if line_breaking else 0.0)
                + PASS_TYPE_DIFFICULTY.get(q.pass_type or "", 0.0)
            )
        return PassQuality(
            distance_m=round(distance, 1),
            difficulty=round(difficulty, 2),
            pressure_on_passer=round(pressure, 2),
            line_breaking=line_breaking,
            forward_m=round(forward, 1),
        )

    def shot_quality(self, event: MatchEvent) -> ShotQuality | None:
        if event.type is not EventType.SHOT:
            return None
        q = event.qualifiers
        distance = math.dist(event.start, GOAL_CENTRE) if event.start else 18.0
        xg = q.xg
        if xg is None:
            xg = location_xg(event.start or (87.0, 34.0), q.body_part, self.pressure(event))
        speed = q.shot_speed_kmh
        if speed is None:
            speed = self.tracking.ball_speed_kmh(event.t)
        return ShotQuality(xg=round(xg, 2), distance_m=round(distance, 1), shot_speed_kmh=speed)


def location_xg(start: tuple[float, float], body_part: str | None, pressure: float) -> float:
    """A simple location model: distance and the angle the goal mouth subtends.

    Roughly 0.23 from the penalty spot, 0.09 from the edge of the box and 0.02 from
    25 m, in line with commonly cited open-play values.
    """
    dx = GOAL_CENTRE[0] - start[0]
    dy = abs(GOAL_CENTRE[1] - start[1])
    distance = math.hypot(dx, dy)
    left = math.atan2(dy - GOAL_HALF_WIDTH_M, max(dx, 0.1))
    right = math.atan2(dy + GOAL_HALF_WIDTH_M, max(dx, 0.1))
    angle = abs(right - left)
    xg = 1 / (1 + math.exp(0.17 * distance - 1.0 * angle))
    if body_part == "head":
        xg *= 0.55
    return clamp(xg * (1 - 0.4 * pressure), 0.01, 0.95)
