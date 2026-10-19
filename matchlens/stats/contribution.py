"""Who made a goal: contribution attribution over the build-up.

**Method** (possession value added, in the spirit of expected threat):

1. Every point on the pitch has a *possession value* ``V``: roughly the chance that a
   team holding the ball there scores from the move. It falls off with distance from
   goal and with the angle away from the centre (``possession_value``).
2. Each on-ball action in the scoring move moves the ball from one value to another.
   A pass or carry is credited with the value it added, ``V(end) - V(start)``; actions
   that lose value (a safe pass backwards) are credited 0, not punished, because they
   kept the move alive.
3. A completed pass's credit is scaled by ``1 + difficulty``, so a hard pass that
   breaks lines is worth more than an easy one covering the same ground.
4. The shot is credited with the shot's xG minus the value of the spot it was taken
   from: the part of the chance the shooter made with the strike itself.
5. Shares are each player's credit over the total, so they sum to 100%.

The result is deterministic and explainable: the evidence dropdown can show every
action's value added. Players with two or more touches in the move count as
contributors even if their share is small, as the Player lens rule requires.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from matchlens.contracts import PITCH_LENGTH_M, PITCH_WIDTH_M, EventType, MatchEvent, Outcome

from .metrics import EventMetrics

ON_BALL = frozenset(
    {
        EventType.PASS,
        EventType.CARRY,
        EventType.SHOT,
        EventType.CORNER,
        EventType.FREE_KICK,
        EventType.THROW_IN,
        EventType.GOAL_KICK,
        EventType.KICK_OFF,
    }
)
DELIVERIES = frozenset(ON_BALL - {EventType.CARRY, EventType.SHOT})
BUILD_UP_WINDOW_S = 25.0


def possession_value(point: tuple[float, float]) -> float:
    """Chance of scoring from holding the ball at ``point`` (attacking frame), 0 to 1."""
    dx = PITCH_LENGTH_M - point[0]
    dy = point[1] - PITCH_WIDTH_M / 2
    distance = math.hypot(dx, dy)
    centrality = 0.5 + 0.5 * math.cos(math.atan2(abs(dy), max(dx, 0.1)))
    return round(0.005 + 0.45 * math.exp(-distance / 12) * centrality, 4)


@dataclass
class ActionCredit:
    event_id: str
    player_id: str
    type: str
    value_before: float
    value_after: float
    credit: float


@dataclass
class Attribution:
    """Contribution shares for one scoring move."""

    shot_event_id: str
    chain: list[ActionCredit]
    shares: dict[str, float]
    touches: dict[str, int]
    events: dict[str, list[str]] = field(default_factory=dict)
    t_start: float = 0.0

    def ranked(self) -> list[tuple[str, float]]:
        return sorted(self.shares.items(), key=lambda kv: (-kv[1], kv[0]))


def build_up(events: list[MatchEvent], shot: MatchEvent) -> list[MatchEvent]:
    """On-ball actions by the scoring team in the move that led to ``shot``.

    The move is the shot's possession, capped at 25 seconds before the shot.
    """
    chain = [
        e
        for e in events
        if e.type in ON_BALL
        and e.team_id == shot.team_id
        and e.t <= shot.t
        and e.t >= shot.t - BUILD_UP_WINDOW_S
        and (shot.possession_id is None or e.possession_id == shot.possession_id)
    ]
    return sorted(chain, key=lambda e: (e.t, e.event_id))


def attribute(metrics: EventMetrics, events: list[MatchEvent], shot: MatchEvent) -> Attribution:
    """Contribution shares for the move ending in ``shot``."""
    chain = build_up(events, shot)
    credits: list[ActionCredit] = []
    for e in chain:
        if e.player_id is None or e.start is None:
            continue
        v0 = possession_value(e.start)
        if e.type is EventType.SHOT:
            quality = metrics.shot_quality(e)
            xg = quality.xg if quality else v0
            credits.append(ActionCredit(e.event_id, e.player_id, e.type, v0, xg, max(xg - v0, 0)))
            continue
        end = e.end or e.start
        v1 = possession_value(end)
        gain = max(v1 - v0, 0.0)
        if e.type in DELIVERIES and e.outcome is Outcome.COMPLETE:
            pq = metrics.pass_quality(e)
            gain *= 1 + (pq.difficulty if pq else 0.0)
        elif e.type in DELIVERIES:
            gain = 0.0
        credits.append(ActionCredit(e.event_id, e.player_id, e.type, v0, v1, round(gain, 4)))

    totals: dict[str, float] = defaultdict(float)
    touches: dict[str, int] = defaultdict(int)
    by_player: dict[str, list[str]] = defaultdict(list)
    for c in credits:
        totals[c.player_id] += c.credit
        touches[c.player_id] += 1
        by_player[c.player_id].append(c.event_id)
    grand = sum(totals.values())
    shares = {
        pid: round(credit / grand, 2) if grand > 0 else round(1 / len(totals), 2)
        for pid, credit in totals.items()
    }
    return Attribution(
        shot_event_id=shot.event_id,
        chain=credits,
        shares=shares,
        touches=dict(touches),
        events=dict(by_player),
        t_start=chain[0].t if chain else shot.t,
    )
