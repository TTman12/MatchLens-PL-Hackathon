"""Match events: one record per on-ball or match event (build plan section 3.3)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict, Field, model_validator

from .common import (
    Clock,
    Contract,
    EventId,
    MatchId,
    MatchTime,
    Period,
    PlayerId,
    Point2,
    PossessionId,
    TeamId,
    Unit,
)


class EventType(StrEnum):
    PASS = "pass"
    CARRY = "carry"
    SHOT = "shot"
    SAVE = "save"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    PRESSURE = "pressure"
    FOUL = "foul"
    CARD = "card"
    CORNER = "corner"
    FREE_KICK = "free_kick"
    THROW_IN = "throw_in"
    GOAL_KICK = "goal_kick"
    GOAL = "goal"
    KICK_OFF = "kick_off"
    SUBSTITUTION = "substitution"
    OFFSIDE = "offside"
    PERIOD_START = "period_start"
    PERIOD_END = "period_end"


class Outcome(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    OUT = "out"
    GOAL = "goal"
    SAVED = "saved"
    BLOCKED = "blocked"
    OFF_TARGET = "off_target"
    POST = "post"
    WON = "won"
    LOST = "lost"
    CAUGHT = "caught"
    PARRIED = "parried"
    YELLOW = "yellow"
    SECOND_YELLOW = "second_yellow"
    RED = "red"


ALLOWED_OUTCOMES: dict[EventType, frozenset[Outcome]] = {
    EventType.PASS: frozenset({Outcome.COMPLETE, Outcome.INCOMPLETE, Outcome.OUT}),
    EventType.CORNER: frozenset({Outcome.COMPLETE, Outcome.INCOMPLETE, Outcome.OUT}),
    EventType.FREE_KICK: frozenset({Outcome.COMPLETE, Outcome.INCOMPLETE, Outcome.OUT}),
    EventType.THROW_IN: frozenset({Outcome.COMPLETE, Outcome.INCOMPLETE, Outcome.OUT}),
    EventType.GOAL_KICK: frozenset({Outcome.COMPLETE, Outcome.INCOMPLETE, Outcome.OUT}),
    EventType.KICK_OFF: frozenset({Outcome.COMPLETE, Outcome.INCOMPLETE}),
    EventType.SHOT: frozenset(
        {Outcome.GOAL, Outcome.SAVED, Outcome.BLOCKED, Outcome.OFF_TARGET, Outcome.POST}
    ),
    EventType.SAVE: frozenset({Outcome.CAUGHT, Outcome.PARRIED}),
    EventType.TACKLE: frozenset({Outcome.WON, Outcome.LOST}),
    EventType.PRESSURE: frozenset({Outcome.WON, Outcome.LOST}),
    EventType.CARD: frozenset({Outcome.YELLOW, Outcome.SECOND_YELLOW, Outcome.RED}),
}
"""Outcomes each event type may carry. Types not listed here carry no outcome."""

TEAMLESS_TYPES = frozenset({EventType.PERIOD_START, EventType.PERIOD_END})
"""Event types that belong to the match, not a team."""


class Qualifiers(Contract):
    """Optional detail on an event. Fields apply only to the event types noted.

    Extra keys are allowed here so the simulator can add detail without a schema
    change; promote a key to a named field once another module depends on it.
    """

    model_config = ConfigDict(extra="allow")

    # Passes and set-piece deliveries
    distance_m: float | None = Field(default=None, ge=0, description="pass, carry, shot")
    difficulty: Unit | None = Field(default=None, description="pass: 0 easy to 1 very hard")
    pressure_on_passer: Unit | None = Field(default=None, description="pass, shot, carry")
    line_breaking: bool | None = Field(default=None, description="pass: bypasses a defensive line")
    pass_type: str | None = Field(
        default=None, description="pass: ground | lofted | cross | through | long | cut_back"
    )
    ball_speed_kmh: float | None = Field(default=None, ge=0, description="pass, shot")
    # Shots
    xg: Unit | None = Field(default=None, description="shot: expected goals")
    shot_speed_kmh: float | None = Field(default=None, ge=0, description="shot")
    body_part: str | None = Field(default=None, description="shot: left_foot | right_foot | head")
    end_height_m: float | None = Field(default=None, ge=0, description="shot: height at goal line")
    # Carries
    duration_s: float | None = Field(default=None, ge=0, description="carry, pressure")
    top_speed_kmh: float | None = Field(default=None, ge=0, description="carry: peak player speed")
    # Discipline
    severity: Unit | None = Field(default=None, description="foul, tackle: how reckless")
    reason: str | None = Field(default=None, description="card, foul: short reason code")
    # Goals
    assist_player_id: PlayerId | None = Field(default=None, description="goal")
    own_goal: bool | None = Field(default=None, description="goal")
    score_home: int | None = Field(default=None, ge=0, description="goal: home score after")
    score_away: int | None = Field(default=None, ge=0, description="goal: away score after")
    # Period end
    added_time_s: float | None = Field(default=None, ge=0, description="period_end")


class MatchEvent(Contract):
    """One on-ball or match event.

    Coordinates are in the **attacking frame** of ``team_id`` (see ``matchlens.contracts.pitch``).

    Conventions:
    - A scoring shot is a ``shot`` with outcome ``goal``, followed by a ``goal`` event at
      the same ``t`` that names the scorer and the score after.
    - ``related_player_id`` is the other player in a two-player event: the player brought
      on (substitution), the player fouled (foul), the ball carrier (tackle, pressure) or
      the shooter (save).
    """

    event_id: EventId
    match_id: MatchId
    t: MatchTime
    period: Period
    clock: Clock
    type: EventType
    team_id: TeamId | None = None
    player_id: PlayerId | None = None
    start: Point2 | None = None
    end: Point2 | None = None
    outcome: Outcome | None = None
    receiver_id: PlayerId | None = Field(default=None, description="pass: intended receiver")
    related_player_id: PlayerId | None = None
    qualifiers: Qualifiers = Field(default_factory=Qualifiers)
    possession_id: PossessionId | None = None

    @model_validator(mode="after")
    def _consistent(self) -> MatchEvent:
        if not self.event_id.startswith(f"{self.match_id}-"):
            raise ValueError("event_id must start with match_id")
        if self.type not in TEAMLESS_TYPES and self.team_id is None:
            raise ValueError(f"{self.type} events need a team_id")
        allowed = ALLOWED_OUTCOMES.get(self.type, frozenset())
        if self.outcome is not None and self.outcome not in allowed:
            raise ValueError(f"outcome {self.outcome} is not valid for a {self.type} event")
        return self
