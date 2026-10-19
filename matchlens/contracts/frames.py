"""Tracking frames: positions of the ball and every player, 10 per second."""

from __future__ import annotations

from .common import Contract, MatchTime, PlayerId, Point3

PlayerState = tuple[float, float, float, float]
"""``[x, y, vx, vy]``: position in metres and velocity in metres per second."""


class Frame(Contract):
    """One tracking frame, in the **pitch frame** (see ``matchlens.contracts.pitch``).

    Stored and streamed as JSON Lines, one frame per line, in ``t`` order. Players who are
    not on the pitch (bench, sent off, substituted) are absent from ``players``.
    """

    t: MatchTime
    ball: Point3
    players: dict[PlayerId, PlayerState]
