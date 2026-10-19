"""Simulate one match and package it in the shared contracts.

    result = simulate_match(league, "ash", "brk", match_id="m291", seed=1325)
    result.meta          # MatchMeta
    result.events        # list[MatchEvent]
    result.iter_frames() # 10 Hz Frame dicts, rendered lazily
    write_match(result, Path("out/m291"))

The same arguments always give the same match.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from matchlens.contracts import (
    SCHEMA_VERSION,
    Frame,
    League,
    MatchEvent,
    MatchMeta,
    WinProbability,
)

from .engine import EngineResult, MatchEngine
from .league import LEAGUE_ID
from .models import pre_match_win_probability
from .render import iter_frames
from .storyline import Storyline

SEASON_ID = "2026"
SEASON_START = date(2026, 8, 15)

REFEREES = [
    "Marta Velling", "Anders Coyle", "Priya Halvorsen", "Desmond Achterberg", "Lena Moravec",
    "Callum Breen", "Ingrid Solano", "Tobias Wren", "Ama Kettering", "Rhys Delacourt",
]  # fmt: skip
WEATHER = [("clear", 0.30), ("overcast", 0.35), ("rain", 0.20), ("wind", 0.15)]


@dataclass
class SimulatedMatch:
    meta: MatchMeta
    events: list[MatchEvent]
    engine: EngineResult = field(repr=False)

    def iter_frames(self) -> Iterator[dict[str, Any]]:
        """Tracking frames at 10 Hz, as plain dicts matching the ``Frame`` contract."""
        return iter_frames(self.engine)


def simulate_match(
    league: League,
    home_id: str,
    away_id: str,
    match_id: str,
    seed: int,
    matchday: int = 1,
    storyline: Storyline | None = None,
    unavailable: frozenset[str] = frozenset(),
    stakes_notes: list[str] | None = None,
    win_prob: WinProbability | None = None,
) -> SimulatedMatch:
    """Play one match. ``unavailable`` players (suspended) are left out of the squad."""
    engine = MatchEngine(league, home_id, away_id, match_id, seed, storyline, unavailable)
    result = engine.run()
    clubs = {c.team_id: c for c in league.clubs}
    home, away = clubs[home_id], clubs[away_id]
    rng = random.Random(seed ^ 0x5EED)
    condition = rng.choices([w for w, _ in WEATHER], [p for _, p in WEATHER])[0]
    kickoff = SEASON_START + timedelta(days=7 * (matchday - 1))
    hour = rng.choice(["12:30", "15:00", "15:00", "17:30", "20:00"])
    sheets = []
    for side, club in enumerate((home, away)):
        sheets.append(
            {
                "team_id": club.team_id,
                "formation": club.formation,
                "starting": [
                    {"player_id": pid, "slot": slot} for pid, slot in result.starting[side]
                ],
                "bench": _bench(club.squad, result.starting[side], unavailable),
            }
        )
    meta = MatchMeta.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "match_id": match_id,
            "league_id": LEAGUE_ID,
            "season_id": SEASON_ID,
            "matchday": matchday,
            "seed": seed,
            "kickoff_local": f"{kickoff.isoformat()}T{hour}:00",
            "stadium": home.stadium,
            "referee": rng.choice(REFEREES),
            "weather": {
                "condition": condition,
                "temperature_c": round(rng.uniform(4, 22), 1),
                "wind_kmh": round(rng.uniform(2, 35 if condition == "wind" else 18), 1),
            },
            "home": sheets[0],
            "away": sheets[1],
            "home_attacks_in_period_1": result.home_direction,
            "stakes": {
                "derby": away_id in home.rival_ids,
                "notes": stakes_notes or [],
            },
            "pre_match_win_prob": (
                win_prob or pre_match_win_probability(home.rating, away.rating)
            ).model_dump(),
        }
    )
    events = [MatchEvent.model_validate(e) for e in result.events]
    return SimulatedMatch(meta, events, result)


def _bench(
    squad: list[Any], starting: list[tuple[str, str]], unavailable: frozenset[str]
) -> list[str]:
    starters = {pid for pid, _ in starting}
    return [
        p.player_id for p in squad if p.player_id not in starters and p.player_id not in unavailable
    ][:9]


def write_match(match: SimulatedMatch, out: Path, frames: bool = True) -> dict[str, Path]:
    """Write ``match.json``, ``events.json`` and ``frames.jsonl`` to ``out``.

    Every frame is validated against the ``Frame`` contract as it is written.
    """
    out.mkdir(parents=True, exist_ok=True)
    paths = {"match": out / "match.json", "events": out / "events.json"}
    _dump(paths["match"], match.meta.model_dump(mode="json"))
    _dump(paths["events"], [e.model_dump(mode="json", exclude_none=True) for e in match.events])
    if frames:
        paths["frames"] = out / "frames.jsonl"
        with paths["frames"].open("w", encoding="utf-8") as fh:
            for frame in match.iter_frames():
                Frame.model_validate(frame)
                fh.write(json.dumps(frame, separators=(",", ":")) + "\n")
    return paths


def _dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
