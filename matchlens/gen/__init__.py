"""Synthetic match generator: events, minute-by-minute stats and hidden ground truth."""

from __future__ import annotations

from typing import Any

from .engine import Match
from .model import build_team, load_league


def generate_match(
    home_id: str, away_id: str, seed: int, match_id: str | None = None, league: dict[str, Any] | None = None
) -> Match:
    league = league or load_league()
    clubs = {c["team_id"]: c for c in league["clubs"]}
    match = Match(
        match_id or f"{home_id}-{away_id}-{seed}", build_team(clubs[home_id], True), build_team(clubs[away_id], False), seed
    )
    match.play()
    return match


__all__ = ["Match", "generate_match"]
