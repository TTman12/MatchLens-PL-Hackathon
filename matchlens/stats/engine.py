"""One entry point to every deterministic stat for a match."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from matchlens.contracts import EventType, Outcome

from .context import SeasonContext
from .contribution import ON_BALL, Attribution, attribute
from .data import MatchData
from .metrics import EventMetrics
from .momentum import Momentum
from .tracking import Tracking
from .win_probability import WinProbabilityModel


@dataclass(frozen=True)
class PlayerMatchStats:
    player_id: str
    touches: int
    passes: int
    passes_complete: int
    pass_accuracy: float | None
    avg_pass_difficulty: float | None
    shots: int
    xg: float
    goals: int
    tackles_won: int
    pressures: int
    top_speed_kmh: float | None
    distance_m: float | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class StatsEngine:
    """Deterministic stats for one match. Agents never compute numbers; they read these."""

    def __init__(self, match: MatchData) -> None:
        self.match = match
        self.tracking = Tracking(match.frames)
        self.metrics = EventMetrics(match, self.tracking)
        self.win_prob = WinProbabilityModel(match)
        self.momentum = Momentum(self.metrics)
        self.context = SeasonContext(match)

    def attribution(self, shot_event_id: str) -> Attribution:
        shot = self.match.events_by_id[shot_event_id]
        return attribute(self.metrics, self.match.events, shot)

    def player_match_stats(self, player_id: str, t: float | None = None) -> PlayerMatchStats:
        """The player's match so far, up to match time ``t`` (default: the whole match)."""
        until = t if t is not None else float("inf")
        own = [e for e in self.match.events if e.player_id == player_id and e.t <= until]
        passes = [e for e in own if e.type is EventType.PASS]
        complete = [e for e in passes if e.outcome is Outcome.COMPLETE]
        difficulties = [
            pq.difficulty for e in passes if (pq := self.metrics.pass_quality(e)) is not None
        ]
        shots = [e for e in own if e.type is EventType.SHOT]
        xg = sum(sq.xg for e in shots if (sq := self.metrics.shot_quality(e)) is not None)
        end = min(until, self.match.frames[-1].t) if self.match.frames else 0.0
        run = self.tracking.run(player_id, 0.0, end) if self.match.frames else None
        return PlayerMatchStats(
            player_id=player_id,
            touches=sum(1 for e in own if e.type in ON_BALL),
            passes=len(passes),
            passes_complete=len(complete),
            pass_accuracy=round(len(complete) / len(passes), 2) if passes else None,
            avg_pass_difficulty=(
                round(sum(difficulties) / len(difficulties), 2) if difficulties else None
            ),
            shots=len(shots),
            xg=round(xg, 2),
            goals=sum(1 for e in own if e.type is EventType.GOAL),
            tackles_won=sum(
                1 for e in own if e.type is EventType.TACKLE and e.outcome is Outcome.WON
            ),
            pressures=sum(1 for e in own if e.type is EventType.PRESSURE),
            top_speed_kmh=run.top_speed_kmh if run else None,
            distance_m=run.distance_m if run else None,
        )
