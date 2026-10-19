"""Working state the agents share while a moment moves through the workflow.

The ``Moment`` contract is what gets published. ``MomentContext`` wraps it with the
detector's working notes (named evidence refs, contributors with their shares, the pass
map) that templates, prompts and the Director need but the contract does not carry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from matchlens.contracts import Draft, Lens, Moment
from matchlens.contracts.cues import Segment
from matchlens.stats.tracking import RunSummary

from .evidence import EvidenceLedger


@dataclass
class Contributor:
    """One player who contributed to a moment, ranked by involvement."""

    player_id: str
    role: str
    events: list[str]
    touches: int
    share: float | None = None
    run: RunSummary | None = None


@dataclass
class MomentContext:
    moment: Moment
    ledger: EvidenceLedger
    contributors: list[Contributor] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    """Display names for every player and club the moment mentions."""
    facts: dict[str, Any] = field(default_factory=dict)
    """Detector facts used to gate agents and pick templates (not numbers to show)."""
    pass_map: list[Segment] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    surprise: float = 0.0
    suspense: float = 0.0

    @property
    def moment_id(self) -> str:
        return self.moment.moment_id

    def sync(self) -> None:
        """Copy the ledger's facts onto the moment record."""
        self.moment.evidence = list(self.ledger.items)

    def contributor(self, player_id: str) -> Contributor | None:
        return next((c for c in self.contributors if c.player_id == player_id), None)


@dataclass
class TemplateRef:
    """How a template-written draft was built, so the Translator can re-render it."""

    key: str
    """Headline string key."""
    params: dict[str, str]
    parts: list[str] = field(default_factory=list)
    """Body sentence keys, in order."""
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class DraftResult:
    """One lens agent instance's output for a moment."""

    key: str
    """Draft key: ``player:<id>``, ``club:<team>`` or ``pundit``."""
    draft: Draft
    template: TemplateRef | None = None
    status: str = "ok"
    """``ok``, ``retried``, ``timeout``, ``error`` or ``gated`` (no model call needed)."""


@dataclass
class LensOutput:
    lens: Lens
    results: list[DraftResult]


@dataclass
class MomentJob:
    """The message that enters the workflow: one detected moment."""

    ctx: MomentContext


@dataclass
class VerifiedMoment:
    ctx: MomentContext
    results: dict[str, DraftResult]
    """Final drafts by key, after verification, repair or fallback. Boxes only."""


@dataclass
class MomentOutcome:
    ctx: MomentContext
    cues: list[dict[str, Any]]
    """Cue dicts for every language, ready to validate into ``Cue`` once ids are assigned."""
