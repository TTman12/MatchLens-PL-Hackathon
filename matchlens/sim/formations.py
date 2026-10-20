"""Formations and the team-shape model.

Every position here is in a team's own **attacking frame** (``x`` from its own goal line
toward the goal it attacks, ``y = 0`` on its right touchline). The engine converts to the
pitch frame with ``matchlens.contracts.pitch``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from matchlens.contracts import PITCH_LENGTH_M, PITCH_WIDTH_M

Slot = tuple[int, str, str, str]
"""``(shirt, position, role, slot)`` for one starter."""

FORMATIONS: dict[str, list[Slot]] = {
    "4-3-3": [
        (1, "GK", "GK", "GK"), (2, "DF", "RB", "RB"), (4, "DF", "CB", "RCB"),
        (5, "DF", "CB", "LCB"), (3, "DF", "LB", "LB"), (6, "MF", "DM", "DM"),
        (8, "MF", "CM", "RCM"), (10, "MF", "CM", "LCM"), (7, "FW", "RW", "RW"),
        (9, "FW", "ST", "ST"), (11, "FW", "LW", "LW"),
    ],
    "4-2-3-1": [
        (1, "GK", "GK", "GK"), (2, "DF", "RB", "RB"), (4, "DF", "CB", "RCB"),
        (5, "DF", "CB", "LCB"), (3, "DF", "LB", "LB"), (6, "MF", "DM", "RDM"),
        (8, "MF", "DM", "LDM"), (7, "MF", "RW", "RAM"), (10, "MF", "AM", "CAM"),
        (11, "MF", "LW", "LAM"), (9, "FW", "ST", "ST"),
    ],
    "3-5-2": [
        (1, "GK", "GK", "GK"), (4, "DF", "CB", "RCB"), (5, "DF", "CB", "CB"),
        (3, "DF", "CB", "LCB"), (2, "MF", "RWB", "RWB"), (6, "MF", "DM", "DM"),
        (8, "MF", "CM", "RCM"), (10, "MF", "CM", "LCM"), (11, "MF", "LWB", "LWB"),
        (9, "FW", "ST", "RS"), (7, "FW", "ST", "LS"),
    ],
    "4-4-2": [
        (1, "GK", "GK", "GK"), (2, "DF", "RB", "RB"), (4, "DF", "CB", "RCB"),
        (5, "DF", "CB", "LCB"), (3, "DF", "LB", "LB"), (7, "MF", "RM", "RM"),
        (8, "MF", "CM", "RCM"), (6, "MF", "CM", "LCM"), (11, "MF", "LM", "LM"),
        (9, "FW", "ST", "RS"), (10, "FW", "ST", "LS"),
    ],
}  # fmt: skip

BENCH: list[tuple[int, str, str]] = [
    (12, "DF", "CB"), (13, "GK", "GK"), (14, "MF", "CM"), (15, "DF", "FB"),
    (16, "MF", "AM"), (17, "FW", "W"), (18, "FW", "ST"),
]  # fmt: skip

SLOT_XY: dict[str, tuple[float, float]] = {
    "GK": (5, 34), "RB": (27, 9), "RCB": (21, 25), "CB": (20, 34), "LCB": (21, 43),
    "LB": (27, 59), "RWB": (33, 7), "LWB": (33, 61), "DM": (33, 34), "RDM": (34, 27),
    "LDM": (34, 41), "RCM": (40, 23), "LCM": (40, 45), "RM": (42, 9), "LM": (42, 59),
    "RAM": (46, 12), "CAM": (45, 34), "LAM": (46, 56), "RW": (47, 9), "LW": (47, 59),
    "ST": (49, 34), "RS": (49, 28), "LS": (49, 40),
}  # fmt: skip
"""Neutral slot positions with the ball on the centre spot, in the attacking frame."""

KICK_OFF_XY: dict[str, tuple[float, float]] = {
    slot: (min(x * 0.92, 50.0), y) for slot, (x, y) in SLOT_XY.items()
}
"""Slot positions at a kick-off: everyone in their own half."""

# How far each line moves up with the ball, in possession and out of it.
_PUSH = {"GK": 0.10, "DF": 0.58, "MF": 0.66, "FW": 0.62}
_FULLBACKS = {"RB", "LB", "RWB", "LWB"}
_WIDE = {"RW", "LW", "RM", "LM", "RAM", "LAM"}


def slot_group(slot: str) -> str:
    """``GK``, ``DF``, ``MF`` or ``FW`` for a formation slot."""
    if slot == "GK":
        return "GK"
    if slot in {"RB", "LB", "RCB", "LCB", "CB"}:
        return "DF"
    if slot in {"ST", "RS", "LS", "RW", "LW"}:
        return "FW"
    return "MF"


@dataclass(frozen=True)
class ShapeContext:
    """What the shape depends on, in the team's attacking frame."""

    ball: tuple[float, float]
    in_possession: bool
    offside_line: float = PITCH_LENGTH_M
    """Deepest outfield opponent, in this team's frame. Attackers stay onside of it."""


def shape_position(slot: str, ctx: ShapeContext) -> tuple[float, float]:
    """Where a player in ``slot`` wants to stand, in the team's attacking frame."""
    sx, sy = SLOT_XY[slot]
    bx, by = ctx.ball
    group = slot_group(slot)
    if group == "GK":
        return keeper_position(ctx.ball, ctx.in_possession)
    push = _PUSH[group]
    if ctx.in_possession:
        x = sx + (bx - 52.5) * push + 5.0
        if slot in _FULLBACKS:
            x += 7.0
        width = 1.15 if slot in _WIDE | _FULLBACKS else 1.05
        y = 34.0 + (sy - 34.0) * width + (by - 34.0) * 0.22
        x = min(x, ctx.offside_line - 0.5)
    else:
        deep = max(0.0, min(1.0, (40.0 - bx) / 25.0))
        """1 when the ball is near this team's own box."""
        x = sx * 0.93 + (bx - 52.5) * (push - 0.06) - 4.0
        y = 34.0 + (sy - 34.0) * (0.80 - 0.22 * deep) + (by - 34.0) * 0.38
        # Lines hold goal side of the ball but never sink onto the goal line.
        floor = {"DF": 6.0, "MF": 11.0, "FW": 24.0}[group]
        if group == "DF":
            x = min(x, bx - 1.5)
        x = max(x, floor)
    return (_clamp(x, 2.0, PITCH_LENGTH_M - 2.0), _clamp(y, 1.5, PITCH_WIDTH_M - 1.5))


def keeper_position(ball: tuple[float, float], in_possession: bool) -> tuple[float, float]:
    """Where a goalkeeper stands, in his team's attacking frame (own goal at ``x = 0``).

    Out of possession he sits on the line from the centre of his goal to the ball,
    narrowing the angle: a step off his line with the ball in the box, up to about
    11 m out (sweeping behind the back line) with the ball in the other half. In
    possession he steps up further to offer a back pass.
    """
    bx, by = ball
    dx, dy = bx, by - 34.0
    d = max(math.hypot(dx, dy), 0.1)
    if in_possession:
        x = 5.0 + max(0.0, bx - 30.0) * 0.18
        return (min(x, 20.0), 34.0 + dy * 0.12)
    r = _clamp(1.0 + 0.11 * d, 1.0, 11.0)
    x = max(0.8, dx / d * r)
    y = 34.0 + _clamp(dy / d * r, -3.2, 3.2)
    return (x, y)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v
