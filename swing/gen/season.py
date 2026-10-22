"""Generate many matches in parallel (a full double round robin by default)."""

from __future__ import annotations

import itertools
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from . import generate_match
from .model import load_league


def fixtures(team_ids: list[str]) -> list[tuple[str, str]]:
    return [(h, a) for h, a in itertools.permutations(team_ids, 2)]


def _one(args: tuple[str, str, int]) -> dict[str, Any]:
    home, away, seed = args
    m = generate_match(home, away, seed)
    return {
        "match_id": m.match_id,
        "home": home,
        "away": away,
        "seed": seed,
        "events": m.events,
        "decisions": m.manager.decisions,
        "physical": m.physical.rows,
        "minutes": m.manager.minutes,
    }


def generate_season(seed: int = 2026, limit: int | None = None, workers: int | None = None) -> list[dict[str, Any]]:
    league = load_league()
    fx = fixtures([c["team_id"] for c in league["clubs"]])
    if limit:
        fx = fx[:limit]
    jobs = [(h, a, seed * 1000 + i) for i, (h, a) in enumerate(fx)]
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as pool:
        return list(pool.map(_one, jobs, chunksize=4))
