"""Momentum and pressure: who is on top, over a rolling five-minute window.

Each team earns *threat points* for what it does in the window: a shot is worth
``2 + 10 x xG``, a corner 1.5, a pass or carry that ends in the final third 1, and a
pressure or tackle that wins the ball back 1. Momentum is ``(home - away) / (home + away)``,
from -1 (the away side is all over them) to +1 (the home side is). It is the Pundit's
"control versus chaos" signal and drives the swing moment.
"""

from __future__ import annotations

from dataclasses import dataclass

from matchlens.contracts import EventType, MatchEvent, Outcome

from .metrics import EventMetrics

WINDOW_S = 300.0
FINAL_THIRD_X = 70.0


@dataclass(frozen=True)
class MomentumPoint:
    t: float
    home_threat: float
    away_threat: float
    momentum: float


def threat_points(metrics: EventMetrics, event: MatchEvent) -> float:
    if event.type is EventType.SHOT:
        quality = metrics.shot_quality(event)
        return 2 + 10 * (quality.xg if quality else 0.05)
    if event.type is EventType.CORNER:
        return 1.5
    if event.type in (EventType.PASS, EventType.CARRY) and event.end is not None:
        complete = event.type is EventType.CARRY or event.outcome is Outcome.COMPLETE
        return 1.0 if complete and event.end[0] >= FINAL_THIRD_X else 0.0
    if event.type in (EventType.PRESSURE, EventType.TACKLE) and event.outcome is Outcome.WON:
        return 1.0
    if event.type is EventType.INTERCEPTION:
        return 1.0
    return 0.0


class Momentum:
    """Momentum series for one match."""

    def __init__(self, metrics: EventMetrics) -> None:
        self.metrics = metrics
        match = metrics.match
        self._points = [
            (e.t, e.team_id == match.home_id, threat_points(metrics, e))
            for e in match.events
            if e.team_id is not None
        ]

    def at(self, t: float) -> MomentumPoint:
        home = sum(p for when, is_home, p in self._points if t - WINDOW_S < when <= t and is_home)
        away = sum(
            p for when, is_home, p in self._points if t - WINDOW_S < when <= t and not is_home
        )
        total = home + away
        value = (home - away) / total if total > 0 else 0.0
        return MomentumPoint(
            t=t, home_threat=round(home, 1), away_threat=round(away, 1), momentum=round(value, 2)
        )

    def series(self, step_s: float = 60.0) -> list[MomentumPoint]:
        """One point per ``step_s`` of match time, for the drama curve and full-time brief."""
        end = max((e.t for e in self.metrics.match.events), default=0.0)
        n = int(end // step_s) + 1
        return [self.at(i * step_s) for i in range(n + 1)]
