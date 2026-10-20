"""The stat catalogue every specialist draws from, and how a change is measured.

Each metric is computed from the per-minute team table over a window [lo, hi). A change is scored
against the spread of the same metric over random windows of the same length taken from the
baseline, so "big" means big for this match, not big in general.
"""

from __future__ import annotations

import statistics as st
from collections.abc import Callable
from dataclasses import dataclass

from .match import MatchData

Fn = Callable[[MatchData, str, int, int], float | None]


@dataclass(frozen=True)
class Metric:
    key: str
    label: str  # what a fan reads on screen
    unit: str
    fn: Fn
    polarity: int  # +1: rises when a team takes control; -1: falls; 0: style, not control
    floor: float  # smallest spread worth trusting, in the metric's units
    family: str  # metrics in one family say the same thing; the Explainer shows one per family


def share(k: str, minimum: float = 6) -> Fn:
    def f(md: MatchData, t: str, lo: int, hi: int) -> float | None:
        x, y = md.total(t, lo, hi, k), md.total(md.opp(t), lo, hi, k)
        return 100 * x / (x + y) if x + y >= minimum else None

    return f


def ratio(num: str, den: str, minimum: float = 5, scale: float = 100) -> Fn:
    def f(md: MatchData, t: str, lo: int, hi: int) -> float | None:
        d = md.total(t, lo, hi, den)
        return scale * md.total(t, lo, hi, num) / d if d >= minimum else None

    return f


def per10(k: str) -> Fn:
    def f(md: MatchData, t: str, lo: int, hi: int) -> float | None:
        n = min(hi, md.last_minute + 1) - max(lo, 0)
        return 10 * md.total(t, lo, hi, k) / n if n > 0 else None

    return f


def per_player_minute(k: str) -> Fn:
    def f(md: MatchData, t: str, lo: int, hi: int) -> float | None:
        pm = md.total(t, lo, hi, "players_on")
        v = md.total(t, lo, hi, k)
        return v / pm if pm > 0 and v > 0 else None

    return f


def ppda(md: MatchData, t: str, lo: int, hi: int) -> float | None:
    """Opposition passes in its own 60% per defensive action there: lower means a harder press."""
    d = md.total(t, lo, hi, "defensive_actions_high")
    p = md.total(md.opp(t), lo, hi, "passes_build_up")
    return p / d if d >= 3 and p >= 10 else None


METRICS: list[Metric] = [
    Metric("field_tilt", "Field tilt", "%", share("touches_final_third", 8), +1, 6, "territory"),
    Metric("possession", "Possession", "%", share("passes", 10), +1, 4, "possession"),
    Metric("pass_accuracy", "Pass accuracy", "%", ratio("passes_completed", "passes", 15), +1, 2, "passing"),
    Metric("final_third_passes", "Passes in final third", "per 10 min", per10("passes_final_third"), +1, 2, "territory"),
    Metric("progressive_passes", "Progressive passes", "per 10 min", per10("progressive_passes"), +1, 1, "progression"),
    Metric("box_entries", "Box entries", "per 10 min", per10("box_entries"), +1, 0.6, "threat"),
    Metric("shots", "Shots", "per 10 min", per10("shots"), +1, 0.5, "threat"),
    Metric("xg", "xG", "per 10 min", per10("xg"), +1, 0.06, "threat"),
    Metric(
        "defending_height", "Defending height", "m", ratio("defensive_action_x_sum", "defensive_actions", 5, 1), +1, 2, "block"
    ),
    Metric("ppda", "Passes allowed per defensive action", "PPDA", ppda, 0, 0.8, "press"),
    Metric("high_turnovers", "High turnovers", "per 10 min", per10("high_regains"), +1, 0.5, "press"),
    Metric("duels_won", "Duels won", "%", ratio("duels_won", "duels", 6), +1, 4, "duels"),
    Metric("long_balls", "Long balls", "% of passes", ratio("long_passes", "passes", 15), 0, 2, "directness"),
    Metric("pass_length", "Average pass length", "m", ratio("pass_length_sum", "passes", 15, 1), 0, 0.8, "directness"),
    Metric("passes", "Passes", "per 10 min", per10("passes"), 0, 3, "tempo"),
    Metric("crosses", "Crosses", "per 10 min", per10("crosses"), 0, 0.5, "width"),
    Metric("duels", "Duels", "per 10 min", per10("duels"), 0, 1.5, "intensity"),
    Metric("fouls", "Fouls", "per 10 min", per10("fouls"), 0, 0.5, "intensity"),
    Metric("distance", "Distance per player", "m per min", per_player_minute("distance_m"), 0, 2, "running"),
    Metric("sprints", "Sprints", "per 10 min", per10("sprints"), 0, 1.5, "running"),
    Metric("hsr", "High-speed running", "m per player per min", per_player_minute("hsr_m"), 0, 0.5, "running"),
]
BY_KEY = {m.key: m for m in METRICS}


def spread(md: MatchData, metric: Metric, team: str, length: int, base_lo: int, base_hi: int) -> float:
    """Standard deviation of the metric over every window of `length` minutes inside the baseline."""
    length = max(length, 3)
    starts = range(base_lo, base_hi - length + 1)
    if len(starts) < 4:  # not enough baseline yet: fall back to everything so far
        starts = range(0, max(base_hi, md.last_minute + 1) - length + 1)
    vals = [v for s in starts if (v := metric.fn(md, team, s, s + length)) is not None]
    sd = st.pstdev(vals) if len(vals) >= 4 else 0.0
    return max(sd, metric.floor)


@dataclass
class Change:
    metric: str
    label: str
    unit: str
    team: str
    before: float
    after: float
    effect_sd: float
    polarity: int
    family: str

    def as_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "label": self.label,
            "unit": self.unit,
            "team": self.team,
            "before": round(self.before, 2),
            "after": round(self.after, 2),
            "effect_sd": round(self.effect_sd, 2),
        }


def change(md: MatchData, metric: Metric, team: str, lo: int, hi: int, baseline: list[tuple[int, int]]) -> Change | None:
    """`after` is the window [lo, hi); `before` is the baseline (a list of minute ranges)."""
    after = metric.fn(md, team, lo, hi)
    if after is None:
        return None
    before = _pooled(md, metric, team, baseline)
    if before is None:
        return None
    b_lo, b_hi = baseline[0][0], baseline[-1][1]
    sd = spread(md, metric, team, hi - lo, b_lo, b_hi)
    return Change(
        metric.key, metric.label, metric.unit, team, before, after, (after - before) / sd, metric.polarity, metric.family
    )


def _pooled(md: MatchData, metric: Metric, team: str, ranges: list[tuple[int, int]]) -> float | None:
    """The metric over several ranges at once, by stitching them into one view of the match."""
    ranges = [(a, b) for a, b in ranges if b > a]
    if not ranges:
        return None
    if len(ranges) == 1:
        return metric.fn(md, team, *ranges[0])
    keep = {m for a, b in ranges for m in range(a, b)}
    stitched = MatchData(
        md.meta,
        [],
        {t: [r for m, r in enumerate(rows) if m in keep] for t, rows in md.team.items()},
        {},
        md.player_team,
        md.names,
        md.roles,
    )
    return metric.fn(stitched, team, 0, len(keep))
