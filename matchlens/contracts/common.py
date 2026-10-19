"""Shared building blocks for every contract: ids, coordinates, time and the base model."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION = "1.0.0"
"""Bumped on any breaking change to a contract. Minor additions bump the middle number."""

PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0
FRAME_RATE_HZ = 10
PERIOD_LENGTH_S = 45 * 60

MatchId = Annotated[str, StringConstraints(pattern=r"^m\d{3,}$")]
"""A match, e.g. ``m042``."""
TeamId = Annotated[str, StringConstraints(pattern=r"^[a-z]{3}$")]
"""A club, three lowercase letters, e.g. ``ash``."""
PlayerId = Annotated[str, StringConstraints(pattern=r"^[a-z]{3}-\d{2}$")]
"""A player, ``<team_id>-<squad number>``, e.g. ``ash-09``."""
EventId = Annotated[str, StringConstraints(pattern=r"^m\d{3,}-e\d{4,}$")]
"""An event, ``<match_id>-e<sequence>``, e.g. ``m042-e0317``."""
PossessionId = Annotated[str, StringConstraints(pattern=r"^m\d{3,}-p\d{3,}$")]
MomentId = Annotated[str, StringConstraints(pattern=r"^m\d{3,}-mo\d{2,}$")]
CueId = Annotated[str, StringConstraints(pattern=r"^m\d{3,}-c\d{3,}$")]
EvidenceId = Annotated[str, StringConstraints(pattern=r"^ev\d+$")]
LanguageCode = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")]
"""BCP 47 language tag, short form, e.g. ``en`` or ``es``."""
Clock = Annotated[str, StringConstraints(pattern=r"^\d{1,3}(\+\d{1,2})?:\d{2}$")]
"""Broadcast clock, e.g. ``23:41`` or ``45+2:14``. Use :func:`format_clock` to build it."""

MatchTime = Annotated[float, Field(ge=0)]
"""Seconds since kick-off on one continuous match timeline.

Period 2 starts where period 1 ended (the half-time break is not on the timeline),
so ``t`` only ever increases. Frames, events, moments and cues all share it.
"""

Probability = Annotated[float, Field(ge=0, le=1)]
Unit = Annotated[float, Field(ge=0, le=1)]
"""A 0 to 1 rating, e.g. pass difficulty or pressure."""

Point2 = tuple[float, float]
"""``[x, y]`` in metres."""
Point3 = tuple[float, float, float]
"""``[x, y, z]`` in metres, z is height above the pitch."""

Period = Literal[1, 2]


class Contract(BaseModel):
    """Base for every contract model. Unknown fields are rejected so drift is caught early."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class WinProbability(Contract):
    """Three-way win probability from the home team's point of view. Sums to 1."""

    home: Probability
    draw: Probability
    away: Probability

    @model_validator(mode="after")
    def _sums_to_one(self) -> WinProbability:
        total = self.home + self.draw + self.away
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"win probabilities must sum to 1, got {total:.3f}")
        return self


def format_clock(t: float, period: int, period_start_t: float) -> str:
    """Broadcast clock for match time ``t``.

    ``period_start_t`` is the match time at which ``period`` kicked off.
    Time past the regulation 45 minutes of a half is shown as added time.
    """
    elapsed = int(t - period_start_t)
    base_minutes = 45 * (period - 1)
    if elapsed < PERIOD_LENGTH_S:
        minutes, seconds = divmod(elapsed, 60)
        return f"{base_minutes + minutes}:{seconds:02d}"
    minutes, seconds = divmod(elapsed - PERIOD_LENGTH_S, 60)
    return f"{base_minutes + 45}+{minutes}:{seconds:02d}"
