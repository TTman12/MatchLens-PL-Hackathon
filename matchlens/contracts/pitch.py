"""Coordinate systems and conversions.

Two frames are used, and every contract says which one it is in:

**Pitch frame** (frames, overlay graphics). Fixed for the whole match.
``x`` runs 0 to 105 m along the pitch, left goal line to right goal line as seen from
the main TV camera. ``y`` runs 0 to 68 m across it, with ``y = 0`` on the touchline
nearest the camera. ``z`` is height.

**Attacking frame** (events). Relative to the team in ``event.team_id``.
``x`` runs 0 to 105 m from that team's own goal line to the goal it attacks.
``y = 0`` is the touchline on its right as it attacks. When a team attacks toward
pitch ``+x`` the two frames coincide; otherwise one is the other rotated 180 degrees.
"""

from __future__ import annotations

from typing import Literal

from .common import PITCH_LENGTH_M, PITCH_WIDTH_M, Point2

Direction = Literal["+x", "-x"]


def attacking_direction(
    home_attacks_in_period_1: Direction, is_home: bool, period: int
) -> Direction:
    """Which way a team attacks in the pitch frame. Teams swap ends at half-time."""
    direction = home_attacks_in_period_1
    if not is_home:
        direction = "-x" if direction == "+x" else "+x"
    if period == 2:
        direction = "-x" if direction == "+x" else "+x"
    return direction


def to_pitch(point: Point2, direction: Direction) -> Point2:
    """Attacking-frame point to pitch frame, for a team attacking ``direction``."""
    x, y = point
    if direction == "+x":
        return (x, y)
    return (PITCH_LENGTH_M - x, PITCH_WIDTH_M - y)


def to_attacking(point: Point2, direction: Direction) -> Point2:
    """Pitch-frame point to the attacking frame of a team attacking ``direction``."""
    # The rotation is its own inverse.
    return to_pitch(point, direction)
