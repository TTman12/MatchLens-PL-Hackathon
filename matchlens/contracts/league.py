"""The fictional league: clubs, squads and player attributes. No real clubs or players."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from .common import Contract, PlayerId, TeamId

Rating = Annotated[int, Field(ge=1, le=99)]
HexColour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class Position(StrEnum):
    GK = "GK"
    DF = "DF"
    MF = "MF"
    FW = "FW"


class Attributes(Contract):
    """Player ratings the simulator draws on, 1 to 99."""

    pace: Rating
    acceleration: Rating
    passing: Rating
    vision: Rating
    finishing: Rating
    tackling: Rating
    keeping: Rating
    discipline: Rating
    stamina: Rating


class Player(Contract):
    player_id: PlayerId
    name: str
    short_name: str = Field(description="Name shown on name tags, e.g. a surname")
    shirt: Annotated[int, Field(ge=1, le=99)]
    position: Position
    role: str = Field(description="Detailed role, e.g. CB, LW, DM, ST")
    foot: Literal["left", "right", "both"]
    top_speed_kmh: Annotated[float, Field(ge=20, le=40)]
    attributes: Attributes


class Colours(Contract):
    primary: HexColour
    secondary: HexColour
    text: HexColour = Field(description="Shirt number colour, readable on primary")


class Club(Contract):
    team_id: TeamId
    name: str
    short_name: str
    city: str
    stadium: str
    colours: Colours
    rating: Rating = Field(description="Pre-match team strength")
    formation: str = Field(description="Default formation, e.g. 4-3-3")
    rival_ids: list[TeamId] = Field(default_factory=list)
    squad: list[Player]


class League(Contract):
    """``league.json``: the fixed universe a season is played in."""

    schema_version: str
    league_id: str
    name: str
    clubs: list[Club]
