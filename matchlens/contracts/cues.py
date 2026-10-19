"""Overlay cues and fact boxes: what the browser (or a broadcast graphics engine) renders.

Cues are timed in match time. The player shows a cue when its playback clock reaches
``t_show``. Agents run once per match, so a cue track holds every lens, every
contributing player and every language; the browser picks what to show locally.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .common import (
    Contract,
    CueId,
    EventId,
    LanguageCode,
    MatchId,
    MatchTime,
    MomentId,
    PlayerId,
    Point2,
    TeamId,
)
from .moment import CameraShot, EvidenceItem

Segment = tuple[float, float, float, float]
"""``[x1, y1, x2, y2]`` in the pitch frame, e.g. one pass on a mini pass map."""


class Layer(StrEnum):
    """Which overlay layer a cue belongs to. The lens sweep swaps the three lens layers."""

    GLOBAL = "global"
    PLAYER = "player"
    CLUB = "club"
    PUNDIT = "pundit"


class Template(StrEnum):
    FACT_BOX = "fact_box"
    """Bottom-third card with headline, body and evidence dropdown."""
    NOT_INVOLVED = "not_involved"
    """Small line for a selected player who did not contribute to this moment."""
    SPEED_BADGE = "speed_badge"
    """Pops when a player passes a speed threshold or a season best."""
    NAME_TAG = "name_tag"
    REPLAY = "replay"
    """Cut to a replay with no box, e.g. the global goal replay."""
    TIMELINE_ITEM = "timeline_item"
    """Below the on-screen threshold: goes to the events rail instead."""
    BRIEF = "brief"
    """Half-time or full-time Pundit brief."""


class AnalystDetail(Contract):
    """Extra depth shown when the evidence dropdown is opened."""

    event_ids: list[EventId] = Field(default_factory=list)
    pass_map: list[Segment] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class FactBox(Contract):
    """The text of a box. Casual viewers see headline and body; analysts open the evidence."""

    headline: str = Field(min_length=1, max_length=80)
    body: str = Field(default="", max_length=280, description="One or two plain sentences")
    evidence: list[EvidenceItem] = Field(default_factory=list)
    analyst: AnalystDetail | None = None


class Camera(Contract):
    shot: CameraShot
    replay: tuple[float, float] | None = Field(default=None, description="Match-time window")
    replay_speed: float = Field(default=0.5, gt=0)
    highlight: PlayerId | None = None
    trail: bool = False
    speedo: float | None = Field(default=None, ge=0, description="Peak speed shown, km/h")
    focus: Point2 | None = Field(default=None, description="Pitch-frame point to frame on")


class SpeedBadge(Contract):
    player_id: PlayerId
    speed_kmh: float = Field(ge=0)
    season_best: bool = False


class Cue(Contract):
    """One timed overlay instruction."""

    cue_id: CueId
    match_id: MatchId
    moment_id: MomentId | None = None
    t_show: MatchTime
    duration: float = Field(gt=0, description="Seconds of playback the cue stays up")
    layer: Layer
    template: Template
    lang: LanguageCode = "en"
    player_id: PlayerId | None = Field(default=None, description="Required on the player layer")
    team_id: TeamId | None = Field(default=None, description="Required on the club layer")
    priority: float = Field(default=0.0, ge=0, description="Importance x relevance")
    box: FactBox | None = None
    camera: Camera | None = None
    badge: SpeedBadge | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Cue:
        if self.layer is Layer.PLAYER and self.player_id is None:
            raise ValueError("player-layer cues need a player_id")
        if self.layer is Layer.CLUB and self.team_id is None:
            raise ValueError("club-layer cues need a team_id")
        boxed = {Template.FACT_BOX, Template.TIMELINE_ITEM, Template.BRIEF}
        if self.template in boxed and self.box is None:
            raise ValueError(f"{self.template} cues need a box")
        if self.template is Template.SPEED_BADGE and self.badge is None:
            raise ValueError("speed_badge cues need a badge")
        if self.template is Template.REPLAY and (self.camera is None or self.camera.replay is None):
            raise ValueError("replay cues need a camera with a replay window")
        return self


class CueTrack(Contract):
    """``cues.json``: every cue for a match, sorted by ``t_show``."""

    schema_version: str
    match_id: MatchId
    languages: list[LanguageCode]
    cues: list[Cue]

    @model_validator(mode="after")
    def _sorted(self) -> CueTrack:
        times = [c.t_show for c in self.cues]
        if times != sorted(times):
            raise ValueError("cues must be sorted by t_show")
        return self
