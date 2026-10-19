"""Turn the engine's movement keyframes and ball segments into 10 Hz tracking frames.

Players move along a cubic Hermite curve through their keyframes, so position and
velocity are smooth and every keyframe (a pass arriving at a receiver's feet, a tackle)
is hit exactly. Tangents are the duration-weighted average of the neighbouring chords,
and zero where the player reverses, which keeps the curve from overshooting. The
period-2 kick-off is a cut: nothing is interpolated across half-time.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterator
from dataclasses import dataclass

from .engine import TICKS_PER_S, BallSegment, EngineResult, MatchPlayer

BALL_RADIUS = 0.11

Vec = tuple[float, float]


@dataclass
class Track:
    """One player's smooth path: keyframe ticks, positions and tangents (m/s)."""

    ticks: list[int]
    points: list[Vec]
    tangents: list[Vec]

    def at(self, tick: float) -> tuple[float, float, float, float]:
        """``(x, y, vx, vy)`` at ``tick``."""
        ts = self.ticks
        i = bisect.bisect_right(ts, tick) - 1
        if i < 0:
            x, y = self.points[0]
            return (x, y, 0.0, 0.0)
        if i >= len(ts) - 1:
            x, y = self.points[-1]
            return (x, y, 0.0, 0.0)
        t0, t1 = ts[i], ts[i + 1]
        h = (t1 - t0) / TICKS_PER_S
        u = (tick - t0) / (t1 - t0)
        (x0, y0), (x1, y1) = self.points[i], self.points[i + 1]
        (a0, b0), (a1, b1) = self.tangents[i], self.tangents[i + 1]
        u2, u3 = u * u, u * u * u
        h00, h10, h01, h11 = 2 * u3 - 3 * u2 + 1, u3 - 2 * u2 + u, -2 * u3 + 3 * u2, u3 - u2
        x = h00 * x0 + h10 * h * a0 + h01 * x1 + h11 * h * a1
        y = h00 * y0 + h10 * h * b0 + h01 * y1 + h11 * h * b1
        d00, d10, d01, d11 = 6 * u2 - 6 * u, 3 * u2 - 4 * u + 1, -6 * u2 + 6 * u, 3 * u2 - 2 * u
        vx = (d00 * x0 + d01 * x1) / h + d10 * a0 + d11 * a1
        vy = (d00 * y0 + d01 * y1) / h + d10 * b0 + d11 * b1
        return (x, y, vx, vy)

    def speeds(self) -> Iterator[float]:
        """Speed at a few points inside every segment, for summaries without rendering."""
        for i in range(len(self.ticks) - 1):
            t0, t1 = self.ticks[i], self.ticks[i + 1]
            for u in (0.25, 0.5, 0.75):
                _, _, vx, vy = self.at(t0 + (t1 - t0) * u)
                yield math.hypot(vx, vy)

    def length(self) -> float:
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:], strict=False))


def build_tracks(player: MatchPlayer) -> list[Track]:
    """A player's keyframes split at half-time cuts, each turned into a :class:`Track`."""
    runs: list[list[tuple[int, float, float]]] = [[]]
    for tick, x, y in player.keyframes:
        if tick < 0:
            runs.append([(-tick, x, y)])
            continue
        run = runs[-1]
        if run and run[-1][0] == tick:
            run[-1] = (tick, x, y)
        else:
            run.append((tick, x, y))
    return [_track(run) for run in runs if run]


def _track(run: list[tuple[int, float, float]]) -> Track:
    ticks = [k[0] for k in run]
    points = [(k[1], k[2]) for k in run]
    n = len(run)
    chords: list[Vec] = []
    for i in range(n - 1):
        h = (ticks[i + 1] - ticks[i]) / TICKS_PER_S
        chords.append(
            ((points[i + 1][0] - points[i][0]) / h, (points[i + 1][1] - points[i][1]) / h)
        )
    tangents: list[Vec] = [(0.0, 0.0)] * n
    for i in range(1, n - 1):
        s0, s1 = chords[i - 1], chords[i]
        if s0[0] * s1[0] + s0[1] * s1[1] <= 0:
            continue
        h0, h1 = ticks[i] - ticks[i - 1], ticks[i + 1] - ticks[i]
        tangents[i] = ((s0[0] * h1 + s1[0] * h0) / (h0 + h1), (s0[1] * h1 + s1[1] * h0) / (h0 + h1))
    return Track(ticks, points, tangents)


def iter_frames(result: EngineResult) -> Iterator[dict[str, object]]:
    """Every tracking frame of the match, in order, as plain dicts in the pitch frame."""
    tracks: dict[str, list[Track]] = {p.pid: build_tracks(p) for p in result.players}
    spans = {
        p.pid: (p.t_on, p.t_off if p.t_off is not None else result.end_tick) for p in result.players
    }
    cut = result.period_starts[1] if len(result.period_starts) > 1 else result.end_tick + 1
    segments = sorted(result.ball, key=lambda s: s.t0)
    starts = [s.t0 for s in segments]
    for tick in range(0, result.end_tick + 1):
        players: dict[str, list[float]] = {}
        for pid, (on, off) in spans.items():
            if not (on <= tick <= off):
                continue
            pt = tracks[pid]
            track = pt[-1] if tick >= cut and len(pt) > 1 else pt[0]
            x, y, vx, vy = track.at(tick)
            players[pid] = [round(x, 2), round(y, 2), round(vx, 2), round(vy, 2)]
        i = bisect.bisect_right(starts, tick) - 1
        ball = _ball_at(segments[i], tick, players) if i >= 0 else (52.5, 34.0, BALL_RADIUS)
        yield {
            "t": round(tick / TICKS_PER_S, 1),
            "ball": [round(ball[0], 2), round(ball[1], 2), round(ball[2], 2)],
            "players": players,
        }


def _ball_at(
    seg: BallSegment, tick: int, players: dict[str, list[float]]
) -> tuple[float, float, float]:
    span = max(1, seg.t1 - seg.t0)
    u = min(1.0, max(0.0, (tick - seg.t0) / span))
    (x0, y0), (x1, y1) = seg.p0, seg.p1
    if seg.kind == "held":
        if seg.holder in players and tick <= seg.t1:
            x, y, vx, vy = players[seg.holder]
            speed = math.hypot(vx, vy)
            if speed > 0.5:
                # Just ahead of the player, in the direction they are running.
                return (x + vx / speed * 0.45, y + vy / speed * 0.45, BALL_RADIUS)
            return (x, y, BALL_RADIUS)
        return (x1, y1, BALL_RADIUS)
    if seg.kind == "still":
        return (x0, y0, BALL_RADIUS)
    if seg.kind == "shot":
        z = BALL_RADIUS + (seg.peak - BALL_RADIUS) * u + 0.6 * 4 * u * (1 - u)
        return (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u, max(BALL_RADIUS, z))
    # A pass or clearance: decelerating, with an arc if lofted.
    f = 1.0 - (1.0 - u) ** 1.5
    z = BALL_RADIUS + 4 * seg.peak * u * (1 - u)
    return (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, z)


def movement_summary(result: EngineResult) -> dict[str, tuple[float, float]]:
    """Distance covered (m) and top speed (km/h) per player, without rendering frames."""
    out: dict[str, tuple[float, float]] = {}
    for p in result.players:
        tracks = build_tracks(p)
        distance = sum(t.length() for t in tracks)
        top = max((s for t in tracks for s in t.speeds()), default=0.0)
        out[p.pid] = (distance, top * 3.6)
    return out
