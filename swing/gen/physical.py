"""Modelled physical output per player per minute: distance, high-speed running and sprints.

Event data has no physical numbers, so these are modelled from typical published elite ranges
(roughly 10 to 12 km per outfield player per match, varying by position) and respond to the
team's plan, ball-in-play time and the player's freshness. Every output row says it is modelled.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .engine import Match

# metres per minute, share of distance above 19.8 km/h, sprints (>25.2 km/h) per minute
ROLE_PHYS: dict[str, tuple[float, float, float]] = {
    "GK": (55, 0.005, 0.01),
    "CB": (98, 0.055, 0.18),
    "RB": (108, 0.09, 0.33),
    "LB": (108, 0.09, 0.33),
    "FB": (108, 0.09, 0.33),
    "RWB": (110, 0.1, 0.36),
    "LWB": (110, 0.1, 0.36),
    "DM": (115, 0.07, 0.22),
    "CM": (120, 0.08, 0.25),
    "AM": (114, 0.085, 0.3),
    "RM": (112, 0.095, 0.33),
    "LM": (112, 0.095, 0.33),
    "RW": (108, 0.1, 0.38),
    "LW": (108, 0.1, 0.38),
    "W": (108, 0.1, 0.38),
    "ST": (102, 0.09, 0.35),
}


def poisson(rng: random.Random, lam: float) -> int:
    k, p, limit = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


class Physical:
    def __init__(self, match: Match) -> None:
        self.m = match
        self.rng = random.Random(match.seed * 104729 + 3)
        self.rows: list[dict[str, Any]] = []

    def minute(self, m: int, bip_seconds: float) -> None:
        bip = min(max(bip_seconds / 60, 0.0), 1.0)
        for team in (self.m.home, self.m.away):
            pl = team.plan
            for p in team.on_pitch:
                base, hsr, spr = ROLE_PHYS.get(p.role, (110, 0.08, 0.28))
                if p.family == "GK":
                    team_f = 1.0
                else:
                    team_f = 1 + 0.06 * pl.press + 0.04 * pl.tempo + 0.04 * pl.block
                dist = base * (0.78 + 0.35 * bip) * team_f * (0.88 + 0.12 * p.fresh) * self.rng.gauss(1, 0.07)
                self.rows.append(
                    {
                        "m": m,
                        "team_id": team.team_id,
                        "player_id": p.player_id,
                        "distance_m": round(max(dist, 0), 1),
                        "hsr_m": round(max(dist * hsr * p.fresh**1.5 * (1 + 0.15 * pl.press) * self.rng.gauss(1, 0.2), 0), 1),
                        "sprints": poisson(self.rng, spr * p.fresh**2 * (0.7 + 0.5 * bip) * (1 + 0.15 * pl.press)),
                    }
                )
