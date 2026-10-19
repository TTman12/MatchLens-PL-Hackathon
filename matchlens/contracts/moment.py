"""The moment record: the shared object every agent reads and writes (build plan 3.4).

Lifecycle: the Moment Detector creates it (``detected``), lens agents add drafts
(``drafted``), the Verifier adds verdicts (``verified``), the Director decides what
is shown and when (``scheduled``) or drops it (``dropped``).

**The evidence rule:** every number in a draft must come from an evidence item the
draft cites. The Verifier rejects a draft whose numbers do not match its evidence.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .common import (
    Contract,
    EventId,
    EvidenceId,
    MatchId,
    MatchTime,
    MomentId,
    Period,
    PlayerId,
    TeamId,
    Unit,
    WinProbability,
)


class MomentType(StrEnum):
    GOAL = "goal"
    CORNER = "corner"
    CARD = "card"
    BIG_SAVE = "big_save"
    BIG_CHANCE = "big_chance"
    SWING = "swing"


class MomentStatus(StrEnum):
    DETECTED = "detected"
    DRAFTED = "drafted"
    VERIFIED = "verified"
    SCHEDULED = "scheduled"
    DROPPED = "dropped"


class Lens(StrEnum):
    PLAYER = "player"
    CLUB = "club"
    PUNDIT = "pundit"


class CameraShot(StrEnum):
    """Camera presets (build plan 3.7)."""

    TV_MAIN = "tv_main"
    SPIDERCAM_GOAL = "spidercam_goal"
    CORNER_LOW = "corner_low"
    CARD_CLOSE = "card_close"
    SAVE_REVERSE = "save_reverse"
    TACTICAL_HIGH = "tactical_high"


class InvolvementRole(StrEnum):
    SCORER = "scorer"
    ASSIST = "assist"
    BUILD_UP = "build_up"
    SHOOTER = "shooter"
    KEEPER = "keeper"
    DEFENDER = "defender"
    FOULER = "fouler"
    FOULED = "fouled"
    TAKER = "taker"


class Involvement(Contract):
    """A player who contributed to the moment. Player agents fan out over this list."""

    player_id: PlayerId
    role: InvolvementRole
    events: list[EventId] = Field(default_factory=list)
    touches: int = Field(default=0, ge=0, description="Touches inside the replay window")
    top_speed_kmh: float | None = Field(default=None, ge=0)
    distance_in_window_m: float | None = Field(default=None, ge=0)


class ClaimType(StrEnum):
    STAT = "stat"
    SEASON = "season"
    TABLE = "table"
    FIXTURE = "fixture"
    DISCIPLINE = "discipline"
    WIN_PROB = "win_prob"
    MILESTONE = "milestone"


class EvidenceItem(Contract):
    """One checkable fact. ``numbers`` holds the machine values the Verifier compares against."""

    id: EvidenceId
    claim_type: ClaimType
    value: str = Field(description="Human-readable statement of the fact")
    source: str = Field(description="An event id or a context ref, e.g. season:ash-09:goals")
    numbers: dict[str, float] = Field(default_factory=dict)


class Draft(Contract):
    """A lens agent's proposed box, or its decision that the moment gets no box."""

    lens: Lens
    subject_id: str | None = Field(
        default=None, description="player_id for the Player lens, team_id for the Club lens"
    )
    kind: Literal["box", "no_box"] = "box"
    headline: str = ""
    body: str = ""
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    author: Literal["agent", "template"] = "agent"
    agent: str | None = Field(default=None, description="Agent instance that wrote it")

    @model_validator(mode="after")
    def _box_has_text(self) -> Draft:
        if self.kind == "box" and not self.headline:
            raise ValueError("a box draft needs a headline")
        return self


class Verdict(Contract):
    """The Verifier's ruling on one draft. ``final`` is the text to show, if any."""

    status: Literal["approved", "repaired", "rejected", "fallback"]
    issues: list[str] = Field(default_factory=list)
    final: Draft | None = None


class DirectorDecision(Contract):
    show: list[str] = Field(default_factory=list, description="Draft keys to put on screen")
    camera: CameraShot = CameraShot.TV_MAIN
    replay_at_t: float | None = Field(default=None, description="Match time the replay starts")
    budget_left: dict[str, int] = Field(
        default_factory=dict, description="Boxes left this half, by lens or player track"
    )


class Drafts(Contract):
    player: dict[PlayerId, Draft] = Field(default_factory=dict)
    club: dict[TeamId, Draft] = Field(default_factory=dict)
    pundit: Draft | None = None


class Moment(Contract):
    """One detected moment and everything the agents have added to it.

    Draft keys, used by ``verdicts`` and ``director.show``: ``player:<player_id>``,
    ``club:<team_id>`` and ``pundit``.
    """

    moment_id: MomentId
    match_id: MatchId
    type: MomentType
    period: Period
    t_start: MatchTime
    t_peak: MatchTime
    t_end: MatchTime
    replay_window: tuple[float, float]
    importance: Unit = Field(description="Detector score; above threshold slows the clock")
    scoring_team: TeamId | None = None
    involved: list[Involvement] = Field(default_factory=list)
    win_prob_before: WinProbability
    win_prob_after: WinProbability
    swing: float = Field(description="Change in home win probability; positive favours home")
    context_refs: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    drafts: Drafts = Field(default_factory=Drafts)
    verdicts: dict[str, Verdict] = Field(default_factory=dict)
    director: DirectorDecision = Field(default_factory=DirectorDecision)
    status: MomentStatus = MomentStatus.DETECTED

    @model_validator(mode="after")
    def _consistent(self) -> Moment:
        if not self.moment_id.startswith(f"{self.match_id}-"):
            raise ValueError("moment_id must start with match_id")
        if not self.t_start <= self.t_peak <= self.t_end:
            raise ValueError("need t_start <= t_peak <= t_end")
        if self.replay_window[0] > self.replay_window[1]:
            raise ValueError("replay_window must run forwards")
        evidence_ids = {item.id for item in self.evidence}
        for key, draft in self._all_drafts():
            missing = set(draft.evidence_ids) - evidence_ids
            if missing:
                raise ValueError(f"draft {key} cites unknown evidence {sorted(missing)}")
        return self

    def _all_drafts(self) -> list[tuple[str, Draft]]:
        drafts = [(f"player:{pid}", d) for pid, d in self.drafts.player.items()]
        drafts += [(f"club:{tid}", d) for tid, d in self.drafts.club.items()]
        if self.drafts.pundit is not None:
            drafts.append(("pundit", self.drafts.pundit))
        return drafts
