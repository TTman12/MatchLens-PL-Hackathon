"""Shared contracts. Every module reads and writes these types; ``schemas/`` is generated from them.

Change a contract in its own pull request, run ``matchlens-schemas`` to regenerate the
JSON Schemas, and bump ``SCHEMA_VERSION`` if the change can break a reader.
"""

from .common import (
    FRAME_RATE_HZ,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    SCHEMA_VERSION,
    WinProbability,
    format_clock,
)
from .cues import AnalystDetail, Camera, Cue, CueTrack, FactBox, Layer, SpeedBadge, Template
from .events import EventType, MatchEvent, Outcome, Qualifiers
from .frames import Frame
from .league import Attributes, Club, Colours, League, Player, Position
from .match import LineupEntry, MatchMeta, Stakes, TeamSheet, Weather
from .moment import (
    CameraShot,
    ClaimType,
    DirectorDecision,
    Draft,
    Drafts,
    EvidenceItem,
    Involvement,
    InvolvementRole,
    Lens,
    Moment,
    MomentStatus,
    MomentType,
    Verdict,
)
from .season import Fixture, PlayerSeasonStats, Score, Season, SeasonRules, TableRow

__all__ = [
    "FRAME_RATE_HZ",
    "PITCH_LENGTH_M",
    "PITCH_WIDTH_M",
    "SCHEMA_VERSION",
    "AnalystDetail",
    "Attributes",
    "Camera",
    "CameraShot",
    "ClaimType",
    "Club",
    "Colours",
    "Cue",
    "CueTrack",
    "DirectorDecision",
    "Draft",
    "Drafts",
    "EventType",
    "EvidenceItem",
    "FactBox",
    "Fixture",
    "Frame",
    "Involvement",
    "InvolvementRole",
    "Layer",
    "League",
    "Lens",
    "LineupEntry",
    "MatchEvent",
    "MatchMeta",
    "Moment",
    "MomentStatus",
    "MomentType",
    "Outcome",
    "Player",
    "PlayerSeasonStats",
    "Position",
    "Qualifiers",
    "Score",
    "Season",
    "SeasonRules",
    "SpeedBadge",
    "Stakes",
    "TableRow",
    "TeamSheet",
    "Template",
    "Verdict",
    "Weather",
    "WinProbability",
    "format_clock",
]
