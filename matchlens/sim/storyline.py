"""Scripted storylines: beats the simulator steers a match toward.

A storyline is a list of beats, each a goal or a card for one side at a given minute. The
engine plays the match normally and, once a beat is due, biases play so it happens
within a few minutes: the scripted side wins the ball back sooner, its attacks run
toward goal and, for a goal, the chosen player gets the shot and scores. In ``strict``
mode every other goal and straight red is turned into a near miss, so the scoreline is
exactly the script's. The build-ups still come from the simulator, so they look like
football rather than a cut scene.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Side = Literal["home", "away"]
BeatKind = Literal["goal", "red", "yellow"]


@dataclass(frozen=True)
class Beat:
    minute: float
    """Broadcast minute the beat becomes due; 45.5 or 90.5 fall in added time."""
    kind: BeatKind
    side: Side
    shirt: int | None = None
    """Who scores or is booked; any suitable player if not given."""


@dataclass(frozen=True)
class Storyline:
    name: str
    beats: tuple[Beat, ...]
    strict: bool = True
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @staticmethod
    def from_json(path: Path) -> Storyline:
        """Load a storyline file: ``{"name", "strict", "beats": [{minute, kind, side}]}``."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        beats = tuple(
            Beat(
                minute=float(b["minute"]),
                kind=b["kind"],
                side=b["side"],
                shirt=b.get("shirt"),
            )
            for b in raw["beats"]
        )
        return Storyline(
            name=raw.get("name", path.stem),
            beats=beats,
            strict=bool(raw.get("strict", True)),
            description=raw.get("description", ""),
        )


STORYLINES: dict[str, Storyline] = {
    "comeback": Storyline(
        name="comeback",
        description=(
            "The away side go 2-0 up before half-time and then lose a man to a straight red. "
            "The home side pull one back, level, and their striker wins it in added time."
        ),
        beats=(
            Beat(17, "goal", "away"),
            Beat(39, "goal", "away"),
            Beat(56, "red", "away"),
            Beat(64, "goal", "home"),
            Beat(78, "goal", "home"),
            Beat(90.5, "goal", "home", shirt=9),
        ),
    ),
    "red_card": Storyline(
        name="red_card",
        description="A first-half straight red changes the match; the rest plays out naturally.",
        strict=False,
        beats=(Beat(34, "red", "away"),),
    ),
    "late_winner": Storyline(
        name="late_winner",
        description="One each going into the last minutes, then the home striker wins it.",
        beats=(
            Beat(28, "goal", "home"),
            Beat(61, "goal", "away"),
            Beat(88, "goal", "home", shirt=9),
        ),
    ),
}


def get_storyline(name_or_path: str) -> Storyline:
    """A built-in storyline by name, or one loaded from a JSON file."""
    if name_or_path in STORYLINES:
        return STORYLINES[name_or_path]
    path = Path(name_or_path)
    if path.exists():
        return Storyline.from_json(path)
    raise ValueError(
        f"unknown storyline {name_or_path!r}; built-in: {', '.join(sorted(STORYLINES))}"
    )
