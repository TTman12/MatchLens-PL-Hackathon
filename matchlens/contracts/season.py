"""Season state before the streamed match: table, fixtures and player season stats."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import Contract, MatchId, PlayerId, TeamId, Unit

Count = Annotated[int, Field(ge=0)]


class SeasonRules(Contract):
    points_for_win: int = 3
    points_for_draw: int = 1
    yellow_card_ban_threshold: int = Field(
        default=5, description="Yellows that trigger a ban; the count resets after the ban"
    )
    ban_length_matches: int = 1


class TableRow(Contract):
    position: Annotated[int, Field(ge=1)]
    team_id: TeamId
    played: Count
    won: Count
    drawn: Count
    lost: Count
    goals_for: Count
    goals_against: Count
    goal_difference: int
    points: Count
    form: list[Literal["W", "D", "L"]] = Field(max_length=5, description="Most recent last")


class Score(Contract):
    home: Count
    away: Count


class Fixture(Contract):
    match_id: MatchId
    matchday: Annotated[int, Field(ge=1)]
    home_id: TeamId
    away_id: TeamId
    status: Literal["played", "scheduled", "live"]
    score: Score | None = None


class PlayerSeasonStats(Contract):
    player_id: PlayerId
    team_id: TeamId
    appearances: Count
    minutes: Count
    goals: Count
    assists: Count
    shots: Count
    passes: Count
    pass_accuracy: Unit | None = None
    avg_pass_difficulty: Unit | None = None
    top_speed_kmh: float | None = Field(default=None, ge=0)
    distance_km: float | None = Field(default=None, ge=0)
    yellow_cards: Count = Field(description="Yellows counting toward the next ban")
    red_cards: Count
    last_goal_matchday: int | None = Field(default=None, description="For milestones")
    suspended_for: list[MatchId] = Field(
        default_factory=list, description="Upcoming matches this player is banned from"
    )


class Season(Contract):
    """``season.json``: everything the agents know before kick-off of the streamed match."""

    schema_version: str
    league_id: str
    season_id: str
    through_matchday: Count = Field(description="Last matchday included in table and stats")
    rules: SeasonRules = Field(default_factory=SeasonRules)
    table: list[TableRow]
    fixtures: list[Fixture]
    players: list[PlayerSeasonStats]
