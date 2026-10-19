"""Match metadata: who is playing, where, and what is at stake."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .common import Contract, MatchId, PlayerId, TeamId, WinProbability
from .pitch import Direction


class LineupEntry(Contract):
    player_id: PlayerId
    slot: str = Field(description="Formation slot, e.g. GK, LCB, RW, ST")


class TeamSheet(Contract):
    team_id: TeamId
    formation: str
    starting: Annotated[list[LineupEntry], Field(min_length=11, max_length=11)]
    bench: list[PlayerId] = Field(default_factory=list)


class Weather(Contract):
    condition: str = Field(description="e.g. clear, overcast, rain, wind")
    temperature_c: float
    wind_kmh: float = Field(ge=0)


class Stakes(Contract):
    derby: bool = False
    notes: list[str] = Field(
        default_factory=list, description="Plain facts, e.g. 'Winner goes top'"
    )


class MatchMeta(Contract):
    """``match.json``: one per match. Player attributes live in ``league.json``."""

    schema_version: str
    match_id: MatchId
    league_id: str
    season_id: str
    matchday: Annotated[int, Field(ge=1)]
    seed: int | None = Field(default=None, description="Simulator seed; null if hand-made")
    kickoff_local: str = Field(description="ISO 8601 local date-time, fictional")
    stadium: str
    referee: str
    weather: Weather
    home: TeamSheet
    away: TeamSheet
    home_attacks_in_period_1: Direction = Field(
        description="Pitch-frame direction the home team attacks in period 1; swaps at half-time"
    )
    stakes: Stakes = Field(default_factory=Stakes)
    pre_match_win_prob: WinProbability
