"""The match engine: plays one seeded match and records events, movement and ball flight.

The engine is event-driven. Each time a player receives the ball it scores the options
open to them (pass to each team-mate, through ball, cross, carry, shot, clearance) from
the positions of everyone on the pitch, picks one with a seeded softmax, and resolves it
with the probability models in :mod:`matchlens.sim.models`. Between those decisions every
player moves toward a target: their slot in the team shape, shifted by the ball, or a pin
when they are part of the action (the receiver running onto a pass, the defender making
a tackle). Movement is speed-limited per player, so the tracking frames rendered from it
by :mod:`matchlens.sim.render` stay physically plausible.

Time is kept in integer ticks of 0.1 s, the frame interval, so events land on frames.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from matchlens.contracts import (
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    Club,
    League,
    Player,
    format_clock,
)
from matchlens.contracts.common import PERIOD_LENGTH_S
from matchlens.contracts.pitch import Direction, attacking_direction, to_attacking, to_pitch

from . import models as m
from .formations import FORMATIONS, KICK_OFF_XY, ShapeContext, shape_position, slot_group
from .storyline import Beat, Storyline

Pt = tuple[float, float]

TICKS_PER_S = 10
PERIOD_TICKS = PERIOD_LENGTH_S * TICKS_PER_S
MAX_STEP_TICKS = 5
"""Longest gap between movement keyframes (0.5 s), short enough to show acceleration."""
PIN_SPEED = 0.64
"""Share of top speed a player may average between keyframes when part of the action."""
SHAPE_SPEED = 0.45
"""Share of top speed for repositioning with the team shape: a jog."""
RUN_SPEED = 0.72
"""Share of top speed for a support run or getting back into shape in a hurry."""
SPRINT_SPEED = 0.9
"""Share of top speed for a run in behind the defence."""
MAX_ACCEL = 7.0
"""Steering acceleration limit, m/s^2 (elite players manage about 6 to 8 from a standing
start). Players speed up and slow down; they never jump to a pace."""
ARRIVE_S = 0.8
"""Arrival: a player slows as they near their target, wanting to get there in about this long."""
SHOT_COST = 0.002
"""Value penalty on a shot: most shots give the ball away."""
CARRY_COST = 0.006
"""Value penalty on a carry, so players move the ball by passing as real teams do."""
PRESS_SPEED = 0.70
"""Share of top speed a defender closes the ball down at."""
WANDER = 0.12
"""How restlessly players drift around their slot, metres per root second."""
SCRIPTED_GOAL_XG = 0.12
"""A scripted goal only comes from a real chance: a shot worth at least this much xG
(easing to half that once the beat is six minutes overdue)."""
HOME_EDGE = 0.035
"""Home advantage: the home side's passes and finishing are this much better, the away side's
this much worse (halved for passes)."""


def ticks(seconds: float) -> int:
    return max(1, round(seconds * TICKS_PER_S))


def _dist(a: Pt, b: Pt) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _on_pitch(p: Pt, margin: float = 0.5) -> Pt:
    return (
        _clamp(p[0], margin, PITCH_LENGTH_M - margin),
        _clamp(p[1], margin, PITCH_WIDTH_M - margin),
    )


def _segment_gap(a: Pt, b: Pt, p: Pt) -> tuple[float, float]:
    """Distance from ``p`` to segment ``ab``, and how far along it (0 to 1) the nearest point is."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length2 = dx * dx + dy * dy
    if length2 < 1e-9:
        return _dist(a, p), 0.0
    u = _clamp(((p[0] - ax) * dx + (p[1] - ay) * dy) / length2, 0.0, 1.0)
    return math.hypot(ax + u * dx - p[0], ay + u * dy - p[1]), u


@dataclass
class MatchPlayer:
    """A player during the match. Positions are in the pitch frame."""

    info: Player
    side: int
    slot: str
    t_on: int
    x: float = 0.0
    y: float = 0.0
    t_off: int | None = None
    keyframes: list[tuple[int, float, float]] = field(default_factory=list)
    velocities: list[Pt] = field(default_factory=list)
    """Velocity (m/s) at each keyframe, the curve's tangent when frames are rendered."""
    wander: Pt = (0.0, 0.0)
    vx: float = 0.0
    vy: float = 0.0
    run: Pt | None = None
    """Pitch-frame target of an off-ball run in progress (in behind, or to support)."""
    run_until: int = 0
    run_pace: float = SHAPE_SPEED
    yellow: bool = False
    sent_off: bool = False

    @property
    def pid(self) -> str:
        return self.info.player_id

    def key(self, tick: int) -> None:
        """Record a movement keyframe at ``tick`` (negative for a cut) with the velocity."""
        self.keyframes.append((tick, self.x, self.y))
        self.velocities.append((self.vx, self.vy))

    @property
    def pos(self) -> Pt:
        return (self.x, self.y)

    @property
    def group(self) -> str:
        return slot_group(self.slot)

    def top_speed(self, tick: int) -> float:
        """Top speed in m/s, lowered by fatigue as minutes on the pitch add up."""
        played = (tick - self.t_on) / (90 * 60 * TICKS_PER_S)
        stamina = self.info.attributes.stamina
        fatigue = 0.075 * min(1.2, played) * (1.0 - stamina / 115)
        return self.info.top_speed_kmh / 3.6 * (1.0 - fatigue)


@dataclass
class TeamState:
    side: int
    club: Club
    formation: str
    rating: float
    on: list[MatchPlayer]
    bench: list[Player]
    starting_slots: list[tuple[str, str]]
    sub_ticks: list[int] = field(default_factory=list)
    subs_made: int = 0

    @property
    def team_id(self) -> str:
        return self.club.team_id


@dataclass
class BallSegment:
    """What the ball does between two ticks, for the renderer."""

    t0: int
    t1: int
    kind: str
    """``held`` (at a player's feet), ``flight``, ``still`` or ``shot``."""
    p0: Pt
    p1: Pt
    holder: str | None = None
    peak: float = 0.0
    """Peak height of a lofted ball, or the height a shot ends at for ``shot``."""


@dataclass
class EngineResult:
    events: list[dict[str, Any]]
    players: list[MatchPlayer]
    ball: list[BallSegment]
    period_starts: list[int]
    end_tick: int
    score: tuple[int, int]
    home_direction: Direction
    starting: tuple[list[tuple[str, str]], list[tuple[str, str]]]
    benches: tuple[list[str], list[str]]


class Restart:
    """A dead ball: who restarts, where (pitch frame) and how."""

    def __init__(self, kind: str, side: int, spot: Pt, setup_s: float) -> None:
        self.kind = kind
        self.side = side
        self.spot = spot
        self.setup_s = setup_s


class MatchEngine:
    def __init__(
        self,
        league: League,
        home_id: str,
        away_id: str,
        match_id: str,
        seed: int,
        storyline: Storyline | None = None,
        unavailable: frozenset[str] = frozenset(),
    ) -> None:
        self.rng = random.Random(seed)
        self.match_id = match_id
        clubs = {c.team_id: c for c in league.clubs}
        self.home_direction: Direction = "+x" if self.rng.random() < 0.5 else "-x"
        self.teams = (
            self._team(0, clubs[home_id], unavailable),
            self._team(1, clubs[away_id], unavailable),
        )
        self.tick = 0
        self.period = 1
        self.period_starts = [0]
        self.events: list[dict[str, Any]] = []
        self.ball_segments: list[BallSegment] = []
        self.ball: Pt = (PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2)
        self.poss = 0
        self.possession_seq = 0
        self.score = [0, 0]
        self.cards_shown = 0
        self.dead_ticks = 0
        self.last_pass: tuple[str, str] | None = None
        """(passer, receiver) of the last completed pass, for assists."""
        self.open_pressure: dict[str, Any] | None = None
        self.storyline = storyline
        self.beats: list[Beat] = (
            sorted(storyline.beats, key=lambda b: b.minute) if storyline else []
        )
        self.all_players: list[MatchPlayer] = [p for t in self.teams for p in t.on]
        self.pressers: set[str] = set()
        self.paces: dict[str, float] = {}

    # ------------------------------------------------------------------------------
    # Set-up
    # ------------------------------------------------------------------------------

    def _team(self, side: int, club: Club, unavailable: frozenset[str]) -> TeamState:
        squad = {p.player_id: p for p in club.squad}
        formation = club.formation
        bench = [p for p in club.squad if p.shirt > 11 and p.player_id not in unavailable]
        slots: list[tuple[str, str]] = []
        on: list[MatchPlayer] = []
        for shirt, position, _role, slot in FORMATIONS[formation]:
            pid = f"{club.team_id}-{shirt:02d}"
            player = squad[pid]
            if pid in unavailable:
                # Pick the bench player who fits the position best.
                same = [b for b in bench if b.position == position] or [
                    b for b in bench if b.position != "GK"
                ]
                player = same[0]
                bench.remove(player)
            slots.append((player.player_id, slot))
            on.append(MatchPlayer(info=player, side=side, slot=slot, t_on=0))
        rating = float(club.rating)
        # Plan three substitution windows between 55 and 85 minutes.
        windows = sorted(self.rng.uniform(55, 86) for _ in range(self.rng.choice([2, 3, 3])))
        sub_ticks = [int(w * 60 * TICKS_PER_S) for w in windows]
        return TeamState(side, club, formation, rating, on, bench, slots, sub_ticks)

    # ------------------------------------------------------------------------------
    # Frames of reference
    # ------------------------------------------------------------------------------

    def direction(self, side: int) -> Direction:
        return attacking_direction(self.home_direction, side == 0, self.period)

    def att(self, side: int, p: Pt) -> Pt:
        return to_attacking(p, self.direction(side))

    def pitch(self, side: int, p: Pt) -> Pt:
        return to_pitch(p, self.direction(side))

    @property
    def t(self) -> float:
        return self.tick / TICKS_PER_S

    def minute(self) -> float:
        """Broadcast minute now, with added time as fractions past 45 or 90."""
        elapsed = (self.tick - self.period_starts[-1]) / TICKS_PER_S / 60
        return elapsed + 45 * (self.period - 1)

    # ------------------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------------------

    def emit(
        self,
        etype: str,
        side: int | None = None,
        player: MatchPlayer | None = None,
        start: Pt | None = None,
        end: Pt | None = None,
        outcome: str | None = None,
        receiver: MatchPlayer | None = None,
        related: MatchPlayer | None = None,
        q: dict[str, Any] | None = None,
        tick: int | None = None,
    ) -> dict[str, Any]:
        t = (self.tick if tick is None else tick) / TICKS_PER_S
        ev: dict[str, Any] = {
            "event_id": f"{self.match_id}-e{len(self.events) + 1:04d}",
            "match_id": self.match_id,
            "t": round(t, 1),
            "period": self.period,
            "clock": format_clock(t, self.period, self.period_starts[-1] / TICKS_PER_S),
            "type": etype,
        }
        if side is not None:
            ev["team_id"] = self.teams[side].team_id
        if player is not None:
            ev["player_id"] = player.pid
        if start is not None and side is not None:
            ev["start"] = _round_pt(self.att(side, start))
        if end is not None and side is not None:
            ev["end"] = _round_pt(self.att(side, end))
        if outcome is not None:
            ev["outcome"] = outcome
        if receiver is not None:
            ev["receiver_id"] = receiver.pid
        if related is not None:
            ev["related_player_id"] = related.pid
        if q:
            ev["qualifiers"] = {k: v for k, v in q.items() if v is not None}
        if self.possession_seq and etype not in ("period_start", "period_end"):
            ev["possession_id"] = f"{self.match_id}-p{self.possession_seq:03d}"
        self.events.append(ev)
        return ev

    def new_possession(self, side: int) -> None:
        if side != self.poss or self.possession_seq == 0:
            self.possession_seq += 1
            self.last_pass = None
        self.poss = side
        if self.open_pressure is not None:
            # The pressing side won the ball back.
            pressing = self.open_pressure.get("team_id")
            self.open_pressure["outcome"] = (
                "won" if pressing == self.teams[side].team_id else "lost"
            )
            self.open_pressure = None

    def close_pressure(self) -> None:
        if self.open_pressure is not None:
            self.open_pressure["outcome"] = "lost"
            self.open_pressure = None

    # ------------------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------------------

    def shapes(self, ball: Pt, poss: int | None, kick_off: bool = False) -> dict[str, Pt]:
        """Where every player wants to be, pitch frame, for the ball at ``ball``.

        The base is each team's shape for this ball position (a ball-driven formation,
        as RoboCup teams interpolate theirs). On top of it the side in possession makes
        off-ball runs (support angles, runs on the last defender's shoulder, overlaps)
        and players drift into pockets of space; the defending side presses with the
        nearest player, covers with the next and marks goal side of the attackers in
        their zone. ``self.paces`` holds the share of top speed each player moves at.
        """
        out: dict[str, Pt] = {}
        self.pressers = set()
        self.paces = {}
        if kick_off or poss is None:
            for team in self.teams:
                for p in team.on:
                    out[p.pid] = self.pitch(team.side, KICK_OFF_XY[p.slot])
                    p.run = None
            return out
        defending = self.teams[1 - poss]
        attacking = self.teams[poss]
        ball_def = self.att(defending.side, ball)
        deepest = PITCH_LENGTH_M
        for p in defending.on:
            sx, sy = shape_position(p.slot, ShapeContext(ball_def, False))
            out[p.pid] = self.pitch(defending.side, (sx, sy))
            if p.group != "GK":
                deepest = min(deepest, self.att(defending.side, p.pos)[0])
                if ball_def[0] < 60:
                    # Ball in our half: everyone gets back into shape at a run.
                    self.paces[p.pid] = RUN_SPEED
            else:
                self.paces[p.pid] = RUN_SPEED  # the keeper keeps cutting the angle
        ball_att = self.att(poss, ball)
        line = max(PITCH_LENGTH_M - deepest, ball_att[0])
        opp_att = [self.att(poss, o.pos) for o in defending.on]
        att_pos: dict[str, Pt] = {
            p.pid: shape_position(p.slot, ShapeContext(ball_att, True, line)) for p in attacking.on
        }
        self.off_ball(attacking, ball_att, line, att_pos, opp_att)
        for pid, pt in att_pos.items():
            out[pid] = self.pitch(poss, pt)
        self.mark(defending, attacking, out)
        # The nearest defender presses the ball, goal side; the next one covers behind.
        outfield = sorted(
            (p for p in defending.on if p.group != "GK"), key=lambda p: _dist(p.pos, ball)
        )
        for p, gap in zip(outfield[:2], (1.3, 5.0), strict=False):
            bx, by = ball_def
            toward_goal = math.atan2(34.0 - by, -bx)
            spot = (bx + math.cos(toward_goal) * gap, by + math.sin(toward_goal) * gap)
            out[p.pid] = self.pitch(defending.side, _on_pitch(spot))
            self.pressers.add(p.pid)
        return out

    def off_ball(
        self,
        team: TeamState,
        ball: Pt,
        line: float,
        pos: dict[str, Pt],
        opps: list[Pt],
    ) -> None:
        """Off-ball movement for the side in possession, in its attacking frame.

        Runs are kept for a few seconds once started, so a player commits to a run
        rather than twitching between targets. The two nearest team-mates offer the ball
        carrier a passing angle; forwards and wide players time runs along the last
        defender; a full-back overlaps a winger on his flank; everyone else edges into
        the most open spot near their slot (a cheap stand-in for pitch control).
        """
        side = team.side
        holder = min(team.on, key=lambda p: _dist(self.att(side, p.pos), ball))
        if _dist(self.att(side, holder.pos), ball) > 3.0:
            holder = None  # type: ignore[assignment]
        movers = [p for p in team.on if p is not holder and p.group != "GK"]
        support = sorted(movers, key=lambda p: _dist(self.att(side, p.pos), ball))[:2]

        def space(pt: Pt) -> float:
            return min((min(_dist(pt, o), 10.0) for o in opps), default=10.0)

        for p in movers:
            if p.run is not None and self.tick < p.run_until:
                pos[p.pid] = self.att(side, p.run)
                self.paces[p.pid] = p.run_pace
                continue
            p.run = None
            here = self.att(side, p.pos)
            sx, sy = pos[p.pid]
            target: Pt | None = None
            pace = RUN_SPEED
            hold_s = self.rng.uniform(1.5, 2.8)
            roll = self.rng.random()
            forward = p.group == "FW" or p.slot in ("CAM", "RAM", "LAM", "RW", "LW")
            if p in support:
                # Offer an angle: an open spot 8 to 14 m from the ball with a clear lane,
                # level or behind it near the box (penetration is the runners' job).
                best, best_v = None, -1e9
                cap_x = line - 0.5 if ball[0] < 70 else ball[0] + 4.0
                for k in range(8):
                    ang = -2.4 + k * (4.8 / 7)
                    r = self.rng.uniform(8, 14)
                    cand = (ball[0] + math.cos(ang) * r, ball[1] + math.sin(ang) * r)
                    cand = (min(cand[0], cap_x), _clamp(cand[1], 2.0, 66.0))
                    lane = min(
                        (min(_segment_gap(ball, cand, o)[0], 4.0) for o in opps), default=4.0
                    )
                    v = min(space(cand), 6.0) + lane - 0.15 * _dist(cand, (sx, sy))
                    if v > best_v:
                        best, best_v = cand, v
                target = best
            elif forward and ball[0] > 38 and here[0] > line - 14 and roll < 0.15:
                # A run on the last defender's shoulder, diagonal into a channel.
                ty = here[1] + (34.0 - here[1]) * 0.45 + self.rng.uniform(-7, 7)
                target = (line - 0.6, _clamp(ty, 4.0, 64.0))
                pace, hold_s = SPRINT_SPEED, self.rng.uniform(1.8, 3.2)
            elif (
                p.slot in ("RB", "LB", "RWB", "LWB")
                and holder is not None
                and ball[0] > 55
                and abs(ball[1] - sy) < 16
                and roll < 0.3
            ):
                # Overlap outside the ball on his flank.
                wide = 3.0 if sy < 34 else 65.0
                target = (min(ball[0] + 9.0, line - 0.5), wide)
                pace, hold_s = SPRINT_SPEED, self.rng.uniform(2.5, 4.0)
            if target is not None:
                p.run = self.pitch(side, _on_pitch(target, 1.0))
                p.run_until = self.tick + ticks(hold_s)
                p.run_pace = pace
                pos[p.pid] = target
                self.paces[p.pid] = pace
                continue
            # Edge into the most open spot near the slot.
            best_pt, best_v = (sx, sy), space((sx, sy))
            for ox, oy in ((4.0, 0.0), (-4.0, 0.0), (0.0, 4.5), (0.0, -4.5)):
                cand = (min(sx + ox, line - 0.5), _clamp(sy + oy, 1.5, 66.5))
                v = space(cand) - 0.6
                if v > best_v:
                    best_pt, best_v = cand, v
            pos[p.pid] = best_pt

    def mark(self, defending: TeamState, attacking: TeamState, out: dict[str, Pt]) -> None:
        """Zonal marking: each defender picks up the nearest free attacker in his zone and
        stands goal side of where that attacker is heading, so runs are tracked, not
        watched. A marker matches a running attacker's pace."""
        goal = self.pitch(defending.side, (0.0, 34.0))
        taken: set[str] = set()
        threats = [p for p in attacking.on if p.group != "GK"]
        for d in sorted(
            (p for p in defending.on if p.group in ("DF", "MF")),
            key=lambda p: 0 if p.group == "DF" else 1,
        ):
            home = out[d.pid]
            cands = [a for a in threats if a.pid not in taken and _dist(out[a.pid], home) < 12.0]
            if not cands:
                continue
            a = min(cands, key=lambda a: _dist(out[a.pid], home))
            taken.add(a.pid)
            ax, ay = out[a.pid]
            gx, gy = goal[0] - ax, goal[1] - ay
            g = math.hypot(gx, gy) or 1.0
            spot = (ax + gx / g * 1.8, ay + gy / g * 1.8)
            w = 0.75 if d.group == "DF" else 0.55
            out[d.pid] = (home[0] * (1 - w) + spot[0] * w, home[1] * (1 - w) + spot[1] * w)
            self.paces[d.pid] = max(RUN_SPEED, self.paces.get(a.pid, SHAPE_SPEED))

    def move(
        self,
        tick_to: int,
        pins: dict[str, Pt] | None = None,
        shape_ball: Pt | None = None,
        targets: dict[str, Pt] | None = None,
        pace: float = SHAPE_SPEED,
        kick_off: bool = False,
    ) -> None:
        """Advance the clock to ``tick_to``, moving every player and recording keyframes.

        ``pins`` must be reached exactly at ``tick_to`` (the engine only pins players to
        points they can reach). Everyone else steers toward their target (Reynolds-style
        seek with arrival): they accelerate and decelerate within ``MAX_ACCEL``, slow down
        as they arrive, and move at their own pace (a jog with the shape, a run to
        support, a sprint in behind). ``targets`` override the team shape at ``pace``.
        """
        pins = pins or {}
        shape = self.shapes(shape_ball or self.ball, self.poss, kick_off)
        paces = self.paces
        if targets:
            shape.update(targets)
            for pid in targets:
                paces.pop(pid, None)
        first = self.tick
        while self.tick < tick_to:
            step = min(MAX_STEP_TICKS, tick_to - self.tick)
            remaining = tick_to - self.tick
            dt = step / TICKS_PER_S
            new_tick = self.tick + step
            amax = MAX_ACCEL * dt
            for team in self.teams:
                for p in team.on:
                    if p.pid in pins:
                        tx, ty = pins[p.pid]
                        frac = step / remaining
                        nx, ny = p.x + (tx - p.x) * frac, p.y + (ty - p.y) * frac
                        limit = PIN_SPEED * p.top_speed(self.tick) * dt * 1.02
                        d = math.hypot(nx - p.x, ny - p.y)
                        if d > limit:
                            nx = p.x + (nx - p.x) * limit / d
                            ny = p.y + (ny - p.y) * limit / d
                        cvx, cvy = (nx - p.x) / dt, (ny - p.y) / dt
                        if self.tick == first and p.velocities:
                            # Ease into the pinned run: the last tangent turns partly toward
                            # it, so the curve doesn't swing wide (and too fast) to make it.
                            ovx, ovy = p.velocities[-1]
                            p.velocities[-1] = (0.7 * ovx + 0.3 * cvx, 0.7 * ovy + 0.3 * cvy)
                        p.vx, p.vy = cvx, cvy
                    else:
                        top = p.top_speed(self.tick)
                        tx, ty = shape[p.pid]
                        if p.pid in self.pressers:
                            share = max(pace, PRESS_SPEED)
                        else:
                            share = paces.get(p.pid, pace)
                            if p.run is None:
                                wx, wy = p.wander
                                jitter = WANDER * (0.3 if p.group == "GK" else 1.0) * math.sqrt(dt)
                                wx = _clamp(wx + self.rng.gauss(0, jitter), -2.0, 2.0)
                                wy = _clamp(wy + self.rng.gauss(0, jitter), -2.0, 2.0)
                                p.wander = (wx, wy)
                                tx, ty = tx + wx, ty + wy
                        dx, dy = tx - p.x, ty - p.y
                        d = math.hypot(dx, dy)
                        if d > 25.0:
                            share = max(share, SPRINT_SPEED)  # caught upfield: a recovery sprint
                        elif d > 15.0:
                            share = max(share, RUN_SPEED)  # out of position: hurry back
                        want = min(share * top, d / ARRIVE_S) if d > 0.8 else 0.0
                        wvx, wvy = (dx / d * want, dy / d * want) if d > 1e-6 else (0.0, 0.0)
                        ax, ay = wvx - p.vx, wvy - p.vy
                        a = math.hypot(ax, ay)
                        if a > amax:
                            ax, ay = ax * amax / a, ay * amax / a
                        ox, oy = p.vx, p.vy
                        p.vx, p.vy = p.vx + ax, p.vy + ay
                        # Trapezoidal step: the rendered curve then never outruns the player.
                        nx, ny = p.x + (ox + p.vx) / 2 * dt, p.y + (oy + p.vy) / 2 * dt
                    cx, cy = _on_pitch((nx, ny), 0.3)
                    if (cx, cy) != (nx, ny):
                        p.vx, p.vy = (cx - p.x) / dt, (cy - p.y) / dt
                    p.x, p.y = cx, cy
                    p.key(new_tick)
            self.tick = new_tick

    def blockers(self, side: int, shooter: Pt) -> int:
        """Outfield opponents between a shooter at ``shooter`` (attacking frame) and goal."""
        return sum(
            1
            for o in self.opponents(side)
            if o.group != "GK" and m.in_shot_triangle(shooter, self.att(side, o.pos))
        )

    def edge(self, side: int, scale: float) -> float:
        """Home-advantage multiplier for ``side``."""
        return 1.0 + HOME_EDGE * scale * (1 if side == 0 else -1)

    def can_reach(self, p: MatchPlayer, target: Pt, seconds: float) -> bool:
        return _dist(p.pos, target) <= PIN_SPEED * p.top_speed(self.tick) * seconds

    def reach_point(self, p: MatchPlayer, target: Pt, seconds: float) -> Pt:
        """``target``, or the closest point to it ``p`` can reach in ``seconds``."""
        limit = PIN_SPEED * p.top_speed(self.tick) * seconds * 0.97
        d = _dist(p.pos, target)
        if d <= limit:
            return target
        f = limit / d
        return (p.x + (target[0] - p.x) * f, p.y + (target[1] - p.y) * f)

    def hold(
        self,
        holder: MatchPlayer,
        seconds: float,
        drift: Pt | None = None,
        pins: dict[str, Pt] | None = None,
    ) -> None:
        """The holder keeps the ball for ``seconds`` while play moves around them."""
        t0 = self.tick
        end = drift or holder.pos
        self.move(t0 + ticks(seconds), pins={**(pins or {}), holder.pid: end})
        self.ball_segments.append(BallSegment(t0, self.tick, "held", self.ball, end, holder.pid))
        self.ball = end

    def flight(self, end: Pt, seconds: float, peak: float = 0.0, kind: str = "flight") -> int:
        """Start a ball flight to ``end``; returns the arrival tick. Movement is the caller's."""
        t1 = self.tick + ticks(seconds)
        self.ball_segments.append(BallSegment(self.tick, t1, kind, self.ball, end, None, peak))
        return t1

    def still(self, seconds: float, spot: Pt, **move_kw: Any) -> None:
        """The ball is dead at ``spot`` for ``seconds``.

        If the ball is elsewhere it is first brought to ``spot`` at a jog, so the ball
        never jumps between frames.
        """
        t0 = self.tick
        last = self.ball_segments[-1].p1 if self.ball_segments else self.ball
        gap = _dist(last, spot)
        fetch = 0.0
        if gap > 0.5:
            fetch = max(1.0, gap / 7.0)
            seconds = max(seconds, fetch + 0.5)
            self.ball_segments.append(BallSegment(t0, t0 + ticks(fetch), "flight", last, spot))
        self.ball = spot
        self.move(t0 + ticks(seconds), **move_kw)
        settled = t0 + ticks(fetch) if fetch else t0
        self.ball_segments.append(BallSegment(settled, self.tick, "still", spot, spot))
        self.dead_ticks += self.tick - t0

    # ------------------------------------------------------------------------------
    # Storyline steering
    # ------------------------------------------------------------------------------

    def due_beat(self) -> Beat | None:
        """The next scripted beat, if its minute has come in the current period."""
        if not self.beats:
            return None
        beat = self.beats[0]
        if _beat_period(beat) != self.period:
            return None
        return beat if self.minute() >= beat.minute else None

    def beat_for(self, kind: str, side: int) -> Beat | None:
        beat = self.due_beat()
        if beat and beat.kind == kind and beat.side == ("home" if side == 0 else "away"):
            return beat
        return None

    def scripted_side(self) -> int | None:
        """The side play is tilted toward while a beat is due.

        For a goal it is the scoring side; for a card it is the other side, so the side
        to be booked is defending when the challenge comes.
        """
        beat = self.due_beat()
        if beat is None:
            return None
        side = 0 if beat.side == "home" else 1
        return side if beat.kind == "goal" else 1 - side

    def overdue(self) -> float:
        """Minutes the due beat has been waiting; steering gets firmer as this grows."""
        beat = self.due_beat()
        return max(0.0, self.minute() - beat.minute) if beat else 0.0

    def scripted_xg(self) -> float:
        """The least xG a scripted goal may come from: a real chance, a little less
        demanding once the beat is well overdue so the script still lands."""
        late = _clamp((self.overdue() - 2.0) / 4.0, 0.0, 1.0)
        return SCRIPTED_GOAL_XG * (1.0 - 0.5 * late)

    def protected(self, team: TeamState) -> set[int]:
        """Shirts named in beats still to come for ``team``: they stay on the pitch."""
        name = "home" if team.side == 0 else "away"
        return {b.shirt for b in self.beats if b.side == name and b.shirt is not None}

    def pending_red(self, side: int) -> bool:
        name = "home" if side == 0 else "away"
        return any(b.kind == "red" and b.side == name for b in self.beats)

    def beat_player(self, beat: Beat, side: int) -> MatchPlayer | None:
        if beat.shirt is None:
            return None
        for p in self.teams[side].on:
            if p.info.shirt == beat.shirt:
                return p
        return None

    # ------------------------------------------------------------------------------
    # The match
    # ------------------------------------------------------------------------------

    def run(self) -> EngineResult:
        kick_side = 0 if self.rng.random() < 0.5 else 1
        for period in (1, 2):
            self.period = period
            if period == 2:
                # The timeline continues from the end of the first half.
                self.tick += 1
                self.period_starts.append(self.tick)
                for p in self.all_players:
                    if p in self.teams[p.side].on:
                        p.x, p.y = self.pitch(p.side, KICK_OFF_XY[p.slot])
                        p.vx = p.vy = 0.0
                        p.run = None
                        p.key(-self.tick)  # negative: a cut
                kick_side = 1 - kick_side
            else:
                for team in self.teams:
                    for p in team.on:
                        p.x, p.y = self.pitch(team.side, KICK_OFF_XY[p.slot])
                        p.key(self.tick)
            self.emit("period_start")
            self.play_period(kick_side)
        for p in self.all_players:
            if p.t_off is None:
                p.t_off = self.tick
        return EngineResult(
            events=self.events,
            players=self.all_players,
            ball=self.ball_segments,
            period_starts=self.period_starts,
            end_tick=self.tick,
            score=(self.score[0], self.score[1]),
            home_direction=self.home_direction,
            starting=(self.teams[0].starting_slots, self.teams[1].starting_slots),
            benches=(
                [p.player_id for p in self.teams[0].bench],
                [p.player_id for p in self.teams[1].bench],
            ),
        )

    def added_time(self) -> int:
        """Seconds of added time, decided when the board goes up."""
        start = self.period_starts[-1]
        stoppages = [
            e
            for e in self.events
            if e["type"] in ("goal", "substitution", "card") and e["t"] * TICKS_PER_S >= start
        ]
        base = 1.0 if self.period == 1 else 2.5
        minutes = base + 0.3 * len(stoppages) + self.rng.random() * 1.8
        return int(min(minutes, 8.0)) * 60

    def play_period(self, kick_side: int) -> None:
        start = self.period_starts[-1]
        added: int | None = None
        restart: Restart | None = Restart(
            "kick_off", kick_side, (PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2), 0.0
        )
        carrier: MatchPlayer | None = None
        while True:
            elapsed = self.tick - start
            if added is None and elapsed >= PERIOD_TICKS - 60 * TICKS_PER_S:
                added = self.added_time()
            if added is not None and elapsed >= PERIOD_TICKS + added * TICKS_PER_S:
                # A scripted beat still to come keeps the half going a little longer.
                late = elapsed >= PERIOD_TICKS + (added + 240) * TICKS_PER_S
                if self.due_beat() is None or late:
                    break
            if restart is not None:
                nxt = self.take_restart(restart)
            else:
                assert carrier is not None
                nxt = self.on_ball(carrier)
            if isinstance(nxt, Restart):
                restart = nxt
                carrier = None
            else:
                restart, carrier = None, nxt
        self.close_pressure()
        start = self.period_starts[-1]
        in_play = (self.tick - start - self.dead_ticks) / TICKS_PER_S
        self.dead_ticks = 0
        self.emit(
            "period_end", q={"added_time_s": float(added or 0), "ball_in_play_s": round(in_play, 1)}
        )
        # Drop any beat meant for a period that has ended.
        self.beats = [b for b in self.beats if _beat_period(b) > self.period]

    # ------------------------------------------------------------------------------
    # Restarts
    # ------------------------------------------------------------------------------

    def take_restart(self, r: Restart) -> MatchPlayer | Restart:
        self.close_pressure()
        team = self.teams[r.side]
        self.new_possession(r.side)
        self.maybe_substitute(r)
        spot_att = self.att(r.side, r.spot)
        if r.kind == "kick_off":
            self.possession_seq += 1
            taker = self.pick(team, ("ST", "RS", "LS", "CAM")) or team.on[-1]
            mate = self.pick(team, ("RCM", "LCM", "DM", "RDM", "LDM", "CAM", "LS", "RS")) or next(
                p for p in team.on if p is not taker
            )
            if not self.can_reach(taker, r.spot, max(r.setup_s, 0.1)):
                r.setup_s = (
                    _dist(taker.pos, r.spot) / (PIN_SPEED * taker.top_speed(self.tick)) + 0.5
                )
            self.still(max(r.setup_s, 0.1), r.spot, kick_off=True, pins={taker.pid: r.spot})
            end = self.pitch(
                r.side,
                (spot_att[0] - self.rng.uniform(6, 14), spot_att[1] + self.rng.uniform(-8, 8)),
            )
            return self.complete_pass(taker, mate, end, "kick_off", q={"pass_type": "ground"})
        if r.kind == "throw_in":
            taker = self.nearest(team, r.spot, groups=("DF", "MF"))
            self.still(r.setup_s, r.spot, pins={taker.pid: r.spot})
            mate, end = self.short_option(taker, max_dist=22)
            return self.restart_pass(taker, mate, end, "throw_in", {"pass_type": "throw"})
        if r.kind == "goal_kick":
            keeper = self.keeper(team)
            spot = self.pitch(r.side, (5.5, self.rng.choice([30.0, 38.0])))
            self.still(r.setup_s, spot, pins={keeper.pid: spot})
            self.ball = spot
            if self.rng.random() < 0.45:
                mate, end = self.short_option(keeper, max_dist=30)
                return self.restart_pass(keeper, mate, end, "goal_kick", {"pass_type": "ground"})
            return self.long_ball(keeper, "goal_kick")
        if r.kind == "corner":
            return self.corner(r)
        if r.kind in ("free_kick", "penalty"):
            return self.free_kick(r)
        raise ValueError(r.kind)

    def maybe_substitute(self, r: Restart) -> None:
        if r.kind == "kick_off" and self.tick == 0:
            return
        for team in self.teams:
            if not team.sub_ticks or self.tick < team.sub_ticks[0]:
                continue
            team.sub_ticks.pop(0)
            n = 1 if not team.sub_ticks else self.rng.choice([1, 2, 2])
            for _ in range(n):
                if team.subs_made >= 5 or not team.bench:
                    break
                self.substitute(team)

    def substitute(self, team: TeamState) -> None:
        keep = self.protected(team)
        outfield = [p for p in team.on if p.group != "GK" and p.info.shirt not in keep]
        if not outfield:
            return

        # Tired players and forwards come off first.
        def tiredness(p: MatchPlayer) -> float:
            return (
                (self.tick - p.t_on) / 600 * (1 - p.info.attributes.stamina / 120)
                + (0.4 if p.group == "FW" else 0.0)
                + (0.6 if p.yellow else 0.0)
                + self.rng.random() * 0.5
            )

        off = max(outfield, key=tiredness)
        want = {"DF": "DF", "MF": "MF", "FW": "FW"}[off.group]
        choices = [b for b in team.bench if b.position == want] or [
            b for b in team.bench if b.position != "GK"
        ]
        if not choices:
            return
        on_info = choices[0]
        team.bench.remove(on_info)
        touchline = (PITCH_LENGTH_M / 2 + self.rng.uniform(-3, 3), 0.5)
        self.move(self.tick + ticks(12), pins={off.pid: self.reach_point(off, touchline, 12)})
        off.t_off = self.tick
        team.on.remove(off)
        new = MatchPlayer(
            info=on_info, side=team.side, slot=off.slot, t_on=self.tick, x=off.x, y=off.y
        )
        new.key(self.tick)
        team.on.append(new)
        self.all_players.append(new)
        team.subs_made += 1
        self.emit("substitution", team.side, off, related=new)
        self.move(self.tick + ticks(8))

    def corner(self, r: Restart) -> MatchPlayer | Restart:
        team = self.teams[r.side]
        other = self.teams[1 - r.side]
        flag_att = (104.5, 0.5 if self.att(r.side, r.spot)[1] < 34 else 67.5)
        flag = self.pitch(r.side, flag_att)
        taker = (
            self.pick(team, ("RW", "LW", "RAM", "LAM", "RM", "LM", "CAM", "RCM", "LCM"))
            or team.on[-1]
        )
        box_targets: dict[str, Pt] = {}
        runners = sorted(
            [p for p in team.on if p.group in ("DF", "FW") and p is not taker],
            key=lambda p: (
                -p.info.attributes.finishing - (20 if p.slot in ("RCB", "LCB", "CB") else 0)
            ),
        )[:5]
        for p in runners:
            box_targets[p.pid] = self.pitch(
                r.side, (self.rng.uniform(92, 100), self.rng.uniform(27, 41))
            )
        for p in other.on:
            if p.group == "GK":
                box_targets[p.pid] = self.pitch(r.side, (104.0, 34.0))
            elif p.group in ("DF", "MF") or self.rng.random() < 0.5:
                box_targets[p.pid] = self.pitch(
                    r.side, (self.rng.uniform(93, 101), self.rng.uniform(28, 40))
                )
        pins = {taker.pid: flag}
        self.still(max(r.setup_s * 0.5, 0.1), flag, targets=box_targets, pace=0.45)
        self.still(max(r.setup_s * 0.5, 0.1), flag, pins=pins, targets=box_targets, pace=0.45)
        taker.x, taker.y = flag
        roll = self.rng.random()
        if roll < 0.15:
            mate, end = self.short_option(taker, max_dist=15)
            return self.restart_pass(taker, mate, end, "corner", {"pass_type": "ground"})
        target_p = self.rng.choice(runners) if runners else self.pick(team, ("ST",)) or team.on[-1]
        aim = target_p.pos
        dist = _dist(flag, aim)
        speed = m.ball_speed(dist, lofted=True)
        secs = m.flight_time(dist, speed, lofted=True)
        q = {
            "pass_type": "cross",
            "ball_speed_kmh": round(speed * 3.6, 1),
            "distance_m": round(dist, 1),
        }
        if roll < 0.15 + 0.30:
            arrive = self.flight(aim, secs, peak=self.rng.uniform(4, 7))
            self.move(arrive, pins={target_p.pid: aim})
            self.ball = aim
            ev = self.emit(
                "corner",
                r.side,
                taker,
                flag,
                aim,
                "complete",
                target_p,
                q=q,
                tick=arrive - ticks(secs),
            )
            ev["qualifiers"]["difficulty"] = 0.55
            self.last_pass = (taker.pid, target_p.pid)
            return self.shot(target_p, header=True)
        # Cleared by a defender.
        defender = self.nearest(other, aim, groups=("DF", "MF", "GK"))
        catch = defender.group == "GK" and self.rng.random() < 0.5
        land = self.reach_point(defender, aim, secs)
        arrive = self.flight(land, secs, peak=self.rng.uniform(4, 7))
        self.move(arrive, pins={defender.pid: land})
        self.ball = land
        self.emit(
            "corner",
            r.side,
            taker,
            flag,
            land,
            "incomplete",
            target_p,
            q=q,
            tick=arrive - ticks(secs),
        )
        self.new_possession(other.side)
        if catch:
            self.emit(
                "save",
                other.side,
                defender,
                land,
                outcome="caught",
                related=target_p,
                q={"claim": True},
            )
            return self.keeper_has_ball(defender)
        if self.rng.random() < 0.25:
            # Headed behind under pressure: another corner.
            return self.deflect_out(defender, "interception", q={"aerial": True})
        self.emit("interception", other.side, defender, land, q={"aerial": True})
        return self.clearance(defender)

    def free_kick(self, r: Restart) -> MatchPlayer | Restart:
        team = self.teams[r.side]
        spot_att = self.att(r.side, r.spot)
        if r.kind == "penalty":
            taker = self.pick(team, ("ST", "RS", "LS", "CAM", "RW", "LW")) or team.on[-1]
            spot = self.pitch(r.side, m.PENALTY_SPOT)
            targets = {
                p.pid: self.pitch(p.side, (self.rng.uniform(30, 40), self.rng.uniform(15, 53)))
                if p.side != r.side
                else self.pitch(p.side, (self.rng.uniform(80, 86), self.rng.uniform(20, 48)))
                for t in self.teams
                for p in t.on
                if p.group != "GK"
            }
            keeper = self.keeper(self.teams[1 - r.side])
            targets[keeper.pid] = self.pitch(r.side, (104.8, 34.0))
            targets.pop(taker.pid, None)
            self.still(r.setup_s, spot, pins={taker.pid: spot}, targets=targets, pace=0.4)
            return self.shot(taker, penalty=True)
        taker = self.pick(team, ("CAM", "RCM", "LCM", "RAM", "LAM", "DM")) or self.nearest(
            team, r.spot
        )
        self.still(r.setup_s, r.spot, pins={taker.pid: r.spot})
        taker.x, taker.y = r.spot
        x, y = spot_att
        if x > 76 and 18 < y < 50 and self.rng.random() < 0.45:
            return self.shot(taker, free_kick=True)
        if x > 70:
            return self.cross(taker, kind="free_kick")
        mate, end = self.short_option(taker, max_dist=35)
        return self.restart_pass(taker, mate, end, "free_kick", {"pass_type": "ground"})

    # ------------------------------------------------------------------------------
    # Player look-ups
    # ------------------------------------------------------------------------------

    def keeper(self, team: TeamState) -> MatchPlayer:
        for p in team.on:
            if p.group == "GK":
                return p
        return team.on[0]

    def pick(self, team: TeamState, slots: tuple[str, ...]) -> MatchPlayer | None:
        for slot in slots:
            for p in team.on:
                if p.slot == slot:
                    return p
        return None

    def nearest(
        self,
        team: TeamState,
        point: Pt,
        groups: tuple[str, ...] = ("DF", "MF", "FW", "GK"),
        exclude: MatchPlayer | None = None,
    ) -> MatchPlayer:
        cands = [p for p in team.on if p.group in groups and p is not exclude] or [
            p for p in team.on if p is not exclude
        ]
        return min(cands, key=lambda p: _dist(p.pos, point))

    def short_option(self, taker: MatchPlayer, max_dist: float) -> tuple[MatchPlayer, Pt]:
        team = self.teams[taker.side]
        mates = [p for p in team.on if p is not taker and p.group != "GK"]
        near = [p for p in mates if _dist(p.pos, taker.pos) <= max_dist] or mates
        mate = min(near, key=lambda p: _dist(p.pos, taker.pos) + self.rng.uniform(0, 12))
        end = _on_pitch(
            (mate.x + self.rng.uniform(-1.5, 1.5), mate.y + self.rng.uniform(-1.5, 1.5)), 1.0
        )
        return mate, end

    # ------------------------------------------------------------------------------
    # Open play
    # ------------------------------------------------------------------------------

    def opponents(self, side: int) -> list[MatchPlayer]:
        return self.teams[1 - side].on

    def on_ball(self, c: MatchPlayer) -> MatchPlayer | Restart:
        """The carrier decides and acts. Returns the next carrier, or a dead ball."""
        side = c.side
        self.ball = c.pos
        b = self.att(side, c.pos)
        opps = self.opponents(side)
        nearest = min(opps, key=lambda p: _dist(p.pos, c.pos))
        gap = _dist(nearest.pos, c.pos)
        pressure = m.pressure_from_distance(gap)
        scripted = self.scripted_side()
        red_beat = self.beat_for("red", 1 - side)
        # A defender close enough may challenge before the carrier acts.
        if c.group != "GK" and (gap < 2.6 or red_beat) and nearest.group != "GK":
            p_challenge = 0.01 + 0.02 * pressure
            if scripted == 1 - side:
                p_challenge += 0.15
            if red_beat and gap < 5.0:
                p_challenge = 1.0
            if self.rng.random() < p_challenge:
                result = self.challenge(nearest, c)
                if result is not None:
                    return result
        return self.decide(c, b, pressure)

    def decide(self, c: MatchPlayer, b: Pt, pressure: float) -> MatchPlayer | Restart:
        side = c.side
        team = self.teams[side]
        opps = [(p, self.att(side, p.pos)) for p in self.opponents(side)]
        options: list[tuple[float, str, Any]] = []
        goal_beat = self.beat_for("goal", side)
        scripted_scorer = self.beat_player(goal_beat, side) if goal_beat else None
        vision = c.info.attributes.vision
        loss_here = 0.75 * m.threat(PITCH_LENGTH_M - b[0], PITCH_WIDTH_M - b[1]) + 0.01

        # Shot
        if b[0] > 68 and c.group != "GK":
            xg = m.expected_goals(b[0], b[1], pressure, blockers=self.blockers(side, b))
            value = xg * (0.85 + 0.3 * c.info.attributes.finishing / 99) - SHOT_COST
            dist = m.goal_distance(*b)
            if dist > 16:
                # Good finishers try their luck from the edge of the box, less so from far out.
                value += 0.08 * c.info.attributes.finishing / 99 * max(0.0, 1 - (dist - 16) / 22)
            if goal_beat and (scripted_scorer is None or scripted_scorer is c):
                # A scripted goal still needs a real chance: shoot from one, else build.
                value = 1.0 if xg >= self.scripted_xg() else value * 0.5
            elif goal_beat and scripted_scorer is not None:
                value *= 0.2
            options.append((value, "shot", None))

        # Passes, through balls and crosses
        for mate in team.on:
            if mate is c:
                continue
            r = self.att(side, mate.pos)
            d = _dist(b, r)
            if d < 4.0 or d > 62.0:
                continue
            if mate.group == "GK" and (b[0] > 40 or pressure < 0.3):
                continue
            if c.group == "GK" and d < 8:
                continue
            target = _on_pitch((min(r[0] + 1.0, 103.0), r[1]), 1.0)
            options.append(
                self.score_pass(
                    c, mate, b, target, pressure, opps, loss_here, "ground", scripted_scorer
                )
            )
            ahead = mate.group in ("FW",) or mate.slot in (
                "CAM",
                "RAM",
                "LAM",
                "RW",
                "LW",
                "RM",
                "LM",
                "RWB",
                "LWB",
            )
            if ahead and r[0] > 50 and r[0] > b[0] + 3 and c.group != "GK":
                lead = self.rng.uniform(7, 15)
                tx = min(r[0] + lead, 100.0)
                ty = r[1] + (34 - r[1]) * 0.25
                through = (tx, ty)
                speed = m.ball_speed(_dist(b, through), False)
                secs = m.flight_time(_dist(b, through), speed, False) + 0.3
                reach = PIN_SPEED * mate.top_speed(self.tick) * secs
                if _dist(r, through) > reach:
                    f = reach / _dist(r, through)
                    through = (r[0] + (through[0] - r[0]) * f, r[1] + (through[1] - r[1]) * f)
                options.append(
                    self.score_pass(
                        c, mate, b, through, pressure, opps, loss_here, "through", scripted_scorer
                    )
                )
        if b[0] > 70 and (b[1] < 22 or b[1] > 46) and c.group != "GK":
            box_mates = [p for p in team.on if p is not c and self.att(side, p.pos)[0] > 78]
            if box_mates:
                cross_value = 0.30 * m.threat(97, 34) - 0.70 * loss_here * 0.3
                if goal_beat:
                    cross_value *= 2
                options.append((cross_value, "cross", None))

        # Carries
        if c.group != "GK":
            heading = math.atan2(34 - b[1], 105 - b[0]) * 0.5
            for k in (-0.9, -0.45, 0.0, 0.45, 0.9):
                ang = heading + k
                length = self.rng.uniform(4, 11)
                end = _on_pitch((b[0] + math.cos(ang) * length, b[1] + math.sin(ang) * length), 1.0)
                dribble = (c.info.attributes.pace + c.info.attributes.acceleration) / 2
                keep = self.carry_keep(b, end, opps, pressure, dribble)
                value = keep * m.threat(*end) - (1 - keep) * loss_here - CARRY_COST
                if scripted_scorer is c and goal_beat:
                    value += 0.2 * max(0.0, end[0] - b[0]) / 10
                options.append((value, "carry", (end, keep)))

        # Clearance under pressure near our own goal
        if b[0] < 30 and pressure > 0.4:
            options.append((0.45 * m.threat(65, 34) - 0.1 * loss_here, "clear", None))

        temperature = 0.0105 * (1.25 - 0.5 * vision / 99)
        if goal_beat:
            temperature *= 0.6
        best = max(v for v, _, _ in options)
        weights = [math.exp((v - best) / temperature) for v, _, _ in options]
        _, kind, payload = self.rng.choices(options, weights)[0]

        if kind == "shot":
            return self.shot(c)
        if kind == "cross":
            return self.cross(c)
        if kind == "carry":
            end, keep = payload
            return self.carry(c, self.pitch(side, end), keep)
        if kind == "clear":
            return self.clearance(c)
        mate, target, pass_type = payload
        return self.play_pass(c, mate, self.pitch(side, target), pass_type, pressure)

    def carry_keep(
        self, b: Pt, end: Pt, opps: list[tuple[MatchPlayer, Pt]], pressure: float, dribble: float
    ) -> float:
        """Chance a carry from ``b`` to ``end`` keeps the ball.

        Each outfield opponent standing in the carry's path is a duel the carrier must
        win, so running at a packed defence is a poor bet and running into space a good one.
        """
        keep = 0.97 - 0.12 * pressure + 0.002 * (dribble - 65)
        for o, op in opps:
            if o.group == "GK":
                continue
            gap, u = _segment_gap(b, end, op)
            if gap < 2.5 and u > 0.05:
                keep *= 0.50 + 0.004 * (dribble - 65)
            elif _dist(end, op) < 3.0:
                keep *= 0.85
        return _clamp(keep, 0.05, 0.97)

    def score_pass(
        self,
        c: MatchPlayer,
        mate: MatchPlayer,
        b: Pt,
        target: Pt,
        pressure: float,
        opps: list[tuple[MatchPlayer, Pt]],
        loss_here: float,
        pass_type: str,
        scripted_scorer: MatchPlayer | None,
    ) -> tuple[float, str, Any]:
        d = _dist(b, target)
        lofted = d > 32
        lane = min((_segment_gap(b, target, o)[0] for _, o in opps), default=30.0)
        if lofted:
            lane *= 1.8
        recv = min((_dist(target, o) for _, o in opps), default=30.0)
        p, _ = m.pass_success(d, lane, recv, pressure, c.info.attributes.passing, lofted)
        if pass_type == "through":
            p *= 0.85
        mid = ((b[0] + target[0]) / 2, (b[1] + target[1]) / 2)
        loss = 0.75 * m.threat(PITCH_LENGTH_M - mid[0], PITCH_WIDTH_M - mid[1]) + 0.01
        value = p * m.threat(*target) - (1 - p) * (loss + loss_here) / 2
        if scripted_scorer is not None or self.beat_for("goal", c.side):
            # Scripted attack: go forward, and find the scorer.
            value += 0.12 * max(0.0, target[0] - b[0]) / 30
            if scripted_scorer is mate:
                value += 0.2
        return (value, "pass", (mate, target, pass_type))

    def lane_info(
        self, side: int, start: Pt, end: Pt
    ) -> tuple[float, float, MatchPlayer | None, float]:
        """Lane gap, receiver gap, the opponent nearest the lane and where along it."""
        lane, best, along = 99.0, None, 0.0
        for o in self.opponents(side):
            g, u = _segment_gap(start, end, o.pos)
            if g < lane and u > 0.08:
                lane, best, along = g, o, u
        recv = min((_dist(end, o.pos) for o in self.opponents(side)), default=30.0)
        return lane, recv, best, along

    def play_pass(
        self,
        c: MatchPlayer,
        mate: MatchPlayer,
        target: Pt,
        pass_type: str,
        pressure: float,
        etype: str = "pass",
    ) -> MatchPlayer | Restart:
        side = c.side
        start = c.pos
        d = _dist(start, target)
        lofted = d > 32 or pass_type == "cross"
        lane, recv, interceptor, along = self.lane_info(side, start, target)
        p, difficulty = m.pass_success(
            d, lane * (1.8 if lofted else 1.0), recv, pressure, c.info.attributes.passing, lofted
        )
        if pass_type == "through":
            p *= 0.85
        p = min(0.995, p * self.edge(side, 0.5))
        scripted = self.scripted_side()
        if scripted == side:
            p = min(0.99, p + 0.25)
        elif scripted == 1 - side:
            p *= max(0.35, 0.75 - 0.08 * self.overdue())
        speed = m.ball_speed(d, lofted)
        secs = m.flight_time(d, speed, lofted)
        b_att, t_att = self.att(side, start), self.att(side, target)
        line_breaking = self.lines_broken(side, b_att, t_att) >= 3
        q: dict[str, Any] = {
            "distance_m": round(d, 1),
            "difficulty": round(difficulty, 2),
            "pressure_on_passer": round(pressure, 2),
            "line_breaking": line_breaking,
            "pass_type": "lofted" if lofted and pass_type == "ground" else pass_type,
            "ball_speed_kmh": round(speed * 3.6, 1),
        }
        # Offside: a through ball or long ball to a runner level with the last defender.
        runner = pass_type == "through" or (lofted and mate.group == "FW")
        if runner and self.rng.random() < (0.11 if pass_type == "through" else 0.05):
            arrive = self.flight(target, secs, peak=3.0 if lofted else 0.0)
            self.move(arrive, pins={c.pid: c.pos, mate.pid: self.reach_point(mate, target, secs)})
            ev = self.emit(
                etype, side, c, start, target, "incomplete", mate, q=q, tick=arrive - ticks(secs)
            )
            ev["qualifiers"]["offside"] = True
            self.emit("offside", side, mate, mate.pos)
            self.ball = mate.pos
            return Restart("free_kick", 1 - side, mate.pos, self.rng.uniform(8, 16))
        if self.rng.random() < p:
            return self.complete_pass(c, mate, target, etype, q, secs, lofted)
        # Failed. Overhit past the receiver, intercepted in the lane, out of play, or lost
        # at the receiver.
        if t_att[0] > 86 and self.rng.random() < 0.6:
            out_att = (105.0, _clamp(t_att[1] + self.rng.uniform(-6, 6), 2.0, 66.0))
            out_pt = self.pitch(side, out_att)
            secs_out = m.flight_time(_dist(start, out_pt), speed, lofted)
            arrive = self.flight(out_pt, secs_out, peak=3.0 if lofted else 0.0)
            self.move(arrive, pins={mate.pid: self.reach_point(mate, target, secs_out)})
            self.ball = out_pt
            ev = self.emit(
                etype, side, c, start, out_pt, "out", mate, q=q, tick=arrive - ticks(secs_out)
            )
            ev["qualifiers"]["distance_m"] = round(_dist(start, out_pt), 1)
            return self.restart_for(out_pt, side)
        if interceptor is not None and lane < 3.0 and self.rng.random() < 0.8:
            point = (
                start[0] + (target[0] - start[0]) * along,
                start[1] + (target[1] - start[1]) * along,
            )
            t_secs = max(0.3, secs * along)
            if self.can_reach(interceptor, point, t_secs + 0.2):
                arrive = self.flight(point, t_secs, peak=2.0 if lofted else 0.0)
                self.move(arrive, pins={interceptor.pid: point})
                self.ball = point
                ev = self.emit(
                    etype,
                    side,
                    c,
                    start,
                    point,
                    "incomplete",
                    mate,
                    q=q,
                    tick=arrive - ticks(t_secs),
                )
                ev["qualifiers"]["distance_m"] = round(_dist(start, point), 1)
                self.new_possession(1 - side)
                self.emit("interception", 1 - side, interceptor, point)
                return interceptor
        t_att_x, t_att_y = t_att
        out_chance = (
            0.5
            if (t_att_y < 6 or t_att_y > 62 or t_att_x > 96)
            else 0.4
            if pass_type == "through"
            else 0.23
            if lofted
            else 0.19
        )
        if self.rng.random() < out_chance:
            over = (t_att_x + (t_att_x - b_att[0]) * 0.35, t_att_y + (t_att_y - b_att[1]) * 0.35)
            out_att = (_clamp(over[0], 1.0, 105.0), _clamp(over[1], 0.0, 68.0))
            if 0.5 < out_att[1] < 67.5 and out_att[0] < 104.5:
                out_att = (out_att[0], 0.0 if out_att[1] < 34 else 68.0)
            out_pt = self.pitch(side, out_att)
            secs_out = m.flight_time(_dist(start, out_pt), speed, lofted)
            arrive = self.flight(out_pt, secs_out, peak=3.0 if lofted else 0.0)
            self.move(arrive, pins={c.pid: c.pos})
            self.ball = out_pt
            ev = self.emit(
                etype, side, c, start, out_pt, "out", mate, q=q, tick=arrive - ticks(secs_out)
            )
            ev["qualifiers"]["distance_m"] = round(_dist(start, out_pt), 1)
            return self.restart_for(out_pt, side)
        # Lost at the receiver: the nearest opponent nicks it.
        defender = min(self.opponents(side), key=lambda o: _dist(o.pos, target))
        point = self.reach_point(defender, target, secs + 0.3)
        arrive = self.flight(point, secs, peak=3.0 if lofted else 0.0)
        reach_mate = self.reach_point(mate, target, secs)
        self.move(arrive, pins={defender.pid: point, mate.pid: reach_mate})
        self.ball = point
        ev = self.emit(
            etype, side, c, start, point, "incomplete", mate, q=q, tick=arrive - ticks(secs)
        )
        ev["qualifiers"]["distance_m"] = round(_dist(start, point), 1)
        self.new_possession(1 - side)
        self.emit("interception", 1 - side, defender, point)
        return defender

    def lines_broken(self, side: int, a: Pt, b: Pt) -> int:
        if b[0] - a[0] < 10:
            return 0
        n = 0
        for o in self.opponents(side):
            ox = self.att(side, o.pos)[0]
            if a[0] + 1 < ox < b[0] - 1 and o.group != "GK":
                n += 1
        return n

    def complete_pass(
        self,
        c: MatchPlayer,
        mate: MatchPlayer,
        target: Pt,
        etype: str,
        q: dict[str, Any] | None = None,
        secs: float | None = None,
        lofted: bool = False,
    ) -> MatchPlayer | Restart:
        side = c.side
        start = c.pos
        d = _dist(start, target)
        if secs is None:
            speed = m.ball_speed(d, lofted)
            secs = m.flight_time(d, speed, lofted)
            q = dict(q or {})
            q.setdefault("distance_m", round(d, 1))
            q.setdefault("ball_speed_kmh", round(speed * 3.6, 1))
        target = self.reach_point(mate, target, secs)
        t0 = self.tick
        arrive = self.flight(target, secs, peak=self.rng.uniform(3, 9) if lofted else 0.0)
        self.move(arrive, pins={mate.pid: target}, shape_ball=target)
        self.ball = target
        self.emit(etype, side, c, start, target, "complete", mate, q=q, tick=t0)
        self.last_pass = (c.pid, mate.pid)
        return self.receive(mate)

    def restart_pass(
        self, taker: MatchPlayer, mate: MatchPlayer, end: Pt, etype: str, q: dict[str, Any]
    ) -> MatchPlayer | Restart:
        taker.x, taker.y = self.ball
        if etype == "throw_in":
            q = {**q, "distance_m": round(_dist(self.ball, end), 1)}
            secs = max(0.6, _dist(self.ball, end) / 11.0)
            return self.complete_pass(taker, mate, end, etype, q, secs, lofted=True)
        pressure = 0.0
        return self.play_pass(taker, mate, end, q.get("pass_type", "ground"), pressure, etype=etype)

    def receive(self, r: MatchPlayer) -> MatchPlayer | Restart:
        """``r`` has just controlled the ball. A defender may close them down."""
        side = r.side
        nearest = min(self.opponents(side), key=lambda o: _dist(o.pos, r.pos))
        gap = _dist(nearest.pos, r.pos)
        touch = self.rng.uniform(0.9, 2.6) * (0.65 if gap < 4 else 1.0)
        if r.group == "GK":
            touch += self.rng.uniform(0.8, 2.5)
        if gap < 5.5 and nearest.group != "GK" and self.rng.random() < 0.75:
            # Close down to about a metre and a half, goal side.
            r_att = self.att(1 - side, r.pos)
            spot = self.pitch(1 - side, (r_att[0] - 1.3, r_att[1]))
            point = self.reach_point(nearest, spot, touch)
            self.close_pressure()
            self.open_pressure = self.emit(
                "pressure", 1 - side, nearest, point, related=r, outcome="lost"
            )
            self.hold(r, touch, pins={nearest.pid: point})
            # A shove or a pull: a foul without a tackle.
            if self.rng.random() < 0.037:
                return self.foul(nearest, r, severity=self.rng.uniform(0.1, 0.6), reason="holding")
        else:
            self.hold(r, touch)
        return r

    def carry(self, c: MatchPlayer, end: Pt, keep: float = 1.0) -> MatchPlayer | Restart:
        """Run with the ball toward ``end``; with probability ``1 - keep`` a defender stops it."""
        side = c.side
        start = c.pos
        scripted = self.scripted_side()
        if scripted == side:
            keep = max(keep, 0.9)
        speed = PIN_SPEED * c.top_speed(self.tick) * self.rng.uniform(0.6, 0.95)
        secs = max(0.6, _dist(start, end) / speed)
        end = self.reach_point(c, end, secs)
        stopped_by: MatchPlayer | None = None
        if self.rng.random() > keep:
            u = self.rng.uniform(0.35, 1.0)
            point = (start[0] + (end[0] - start[0]) * u, start[1] + (end[1] - start[1]) * u)
            defender = min(self.opponents(side), key=lambda o: _dist(o.pos, point))
            if defender.group != "GK" and self.can_reach(defender, point, secs * u + 0.2):
                stopped_by, end, secs = defender, point, max(0.4, secs * u)
        d = _dist(start, end)
        t0 = self.tick
        pins = {c.pid: end}
        if stopped_by is not None:
            pins[stopped_by.pid] = end
        self.move(t0 + ticks(secs), pins=pins, shape_ball=end)
        self.ball_segments.append(BallSegment(t0, self.tick, "held", start, end, c.pid))
        self.ball = end
        avg = d / secs * 3.6
        if d >= 1.0:
            self.emit(
                "carry", side, c, start, end,
                q={"distance_m": round(d, 1), "duration_s": round(secs, 1),
                   "top_speed_kmh": round(min(avg * 1.35, c.top_speed(t0) * 3.6), 1)},
                tick=t0,
            )  # fmt: skip
        if stopped_by is None:
            return c
        # Dispossessed: a clean tackle, a foul, or a heavy touch the defender collects.
        roll = self.rng.random()
        disc = stopped_by.info.attributes.discipline
        if roll < 0.06 + 0.08 * (1 - disc / 99):
            return self.foul(stopped_by, c, self.rng.random() ** 0.8, reason="tackle")
        self.new_possession(1 - side)
        if roll < 0.35:
            self.emit("tackle", 1 - side, stopped_by, end, outcome="won", related=c)
        else:
            self.emit("interception", 1 - side, stopped_by, end, q={"loose_ball": True})
        return self.receive(stopped_by)

    def clearance(self, c: MatchPlayer) -> MatchPlayer | Restart:
        return self.long_ball(c, "pass", clearance=True)

    def long_ball(
        self, c: MatchPlayer, etype: str, clearance: bool = False
    ) -> MatchPlayer | Restart:
        side = c.side
        team = self.teams[side]
        start = c.pos
        fwds = [p for p in team.on if p.group in ("FW", "MF") and p is not c] or [
            p for p in team.on if p is not c
        ]
        mate = max(fwds, key=lambda p: self.att(side, p.pos)[0] + self.rng.uniform(0, 15))
        r = self.att(side, mate.pos)
        target = self.pitch(
            side, _on_pitch((r[0] + self.rng.uniform(-3, 6), r[1] + self.rng.uniform(-6, 6)), 2.0)
        )
        d = _dist(c.pos, target)
        pass_type = "clearance" if clearance else "long"
        lane, recv, _, _ = self.lane_info(side, c.pos, target)
        p, diff = m.pass_success(
            d, lane * 2.0, recv, 0.3 if clearance else 0.0, c.info.attributes.passing, True
        )
        p *= 0.75 if clearance else 0.9
        speed = m.ball_speed(d, True)
        secs = m.flight_time(d, speed, True)
        broken = self.lines_broken(side, self.att(side, c.pos), self.att(side, target))
        q = {"distance_m": round(d, 1), "difficulty": round(diff, 2), "pass_type": pass_type,
             "ball_speed_kmh": round(speed * 3.6, 1), "line_breaking": broken >= 3}  # fmt: skip
        if self.rng.random() < p:
            return self.complete_pass(c, mate, target, etype, q, secs, lofted=True)
        if clearance and self.rng.random() < 0.3:
            if self.att(side, start)[0] < 20 and self.rng.random() < 0.35:
                # Sliced behind his own goal line: a corner to the attackers.
                return self.deflect_out(c, etype, q={**q, "pass_type": pass_type}, outcome="out")
            out_att = (self.att(side, target)[0], 0.0 if self.att(side, target)[1] < 34 else 68.0)
            out_pt = self.pitch(side, out_att)
            secs_out = m.flight_time(_dist(start, out_pt), speed, True)
            arrive = self.flight(out_pt, secs_out, peak=8.0)
            self.move(arrive)
            self.ball = out_pt
            self.emit(
                etype, side, c, start, out_pt, "out", mate, q=q, tick=arrive - ticks(secs_out)
            )
            return self.restart_for(out_pt, side)
        defender = min(self.opponents(side), key=lambda o: _dist(o.pos, target))
        point = self.reach_point(defender, target, secs + 0.4)
        arrive = self.flight(point, secs, peak=self.rng.uniform(6, 12))
        self.move(
            arrive, pins={defender.pid: point, mate.pid: self.reach_point(mate, target, secs)}
        )
        self.ball = point
        self.emit(etype, side, c, start, point, "incomplete", mate, q=q, tick=arrive - ticks(secs))
        self.new_possession(1 - side)
        self.emit("interception", 1 - side, defender, point, q={"aerial": True})
        return self.receive(defender)

    def cross(self, c: MatchPlayer, kind: str = "pass") -> MatchPlayer | Restart:
        side = c.side
        team = self.teams[side]
        targets = [p for p in team.on if p is not c and p.group != "GK"]
        mate = max(
            targets,
            key=lambda p: (
                self.att(side, p.pos)[0] + self.rng.uniform(0, 10) + (8 if p.group == "FW" else 0)
            ),
        )
        aim_att = (self.rng.uniform(93, 100), self.rng.uniform(28, 40))
        start = c.pos
        aim = self.pitch(side, aim_att)
        d = _dist(start, aim)
        speed = m.ball_speed(d, True)
        secs = m.flight_time(d, speed, True)
        aim = self.reach_point(mate, aim, secs + 0.2)
        pressure = m.pressure_from_distance(min(_dist(o.pos, start) for o in self.opponents(side)))
        p = 0.20 + 0.12 * c.info.attributes.passing / 99
        # Crosses into a crowded box are cleared; a box with runners in it is a target.
        in_box = [m.in_box(*self.att(side, q.pos)) for q in self.teams[side].on]
        def_box = [m.in_box(*self.att(side, q.pos)) for q in self.opponents(side)]
        p *= _clamp(1.0 + 0.1 * (sum(in_box) - sum(def_box) + 2), 0.5, 1.15)
        goal_beat = self.beat_for("goal", side)
        if goal_beat:
            p = 0.8
        elif self.scripted_side() == 1 - side:
            p *= 0.6
        q = {"distance_m": round(d, 1), "difficulty": round(1 - p, 2), "pass_type": "cross",
             "pressure_on_passer": round(pressure, 2), "ball_speed_kmh": round(speed * 3.6, 1),
             "line_breaking": False}  # fmt: skip
        if self.rng.random() < p:
            t0 = self.tick
            arrive = self.flight(aim, secs, peak=self.rng.uniform(3, 6))
            self.move(arrive, pins={mate.pid: aim}, shape_ball=aim)
            self.ball = aim
            self.emit(kind, side, c, start, aim, "complete", mate, q=q, tick=t0)
            self.last_pass = (c.pid, mate.pid)
            if self.rng.random() < 0.55:
                return self.shot(mate, header=True)
            return self.receive(mate)
        other = self.teams[1 - side]
        if self.rng.random() < 0.3:
            # Overhit: over everyone and out for a goal kick.
            out_att = (105.0, self.rng.uniform(20, 48))
            out_pt = self.pitch(side, out_att)
            t0 = self.tick
            arrive = self.flight(out_pt, secs * 1.3, peak=self.rng.uniform(3, 6))
            self.move(arrive)
            self.ball = out_pt
            self.emit(kind, side, c, start, out_pt, "out", mate, q=q, tick=t0)
            return self.restart_for(out_pt, side)
        defender = self.nearest(other, aim, groups=("DF", "GK", "MF"))
        land = self.reach_point(defender, aim, secs + 0.3)
        t0 = self.tick
        arrive = self.flight(land, secs, peak=self.rng.uniform(3, 6))
        self.move(arrive, pins={defender.pid: land, mate.pid: self.reach_point(mate, aim, secs)})
        self.ball = land
        ev = self.emit(kind, side, c, start, land, "incomplete", mate, q=q, tick=t0)
        ev["qualifiers"]["distance_m"] = round(_dist(start, land), 1)
        self.new_possession(other.side)
        if defender.group == "GK" and self.rng.random() < 0.7:
            self.emit(
                "save",
                other.side,
                defender,
                land,
                outcome="caught",
                related=mate,
                q={"claim": True},
            )
            return self.keeper_has_ball(defender)
        if self.rng.random() < 0.45:
            # Headed behind for a corner.
            return self.deflect_out(defender, "interception", q={"aerial": True})
        self.emit("interception", other.side, defender, land, q={"aerial": True})
        return self.clearance(defender)

    # ------------------------------------------------------------------------------
    # Duels and discipline
    # ------------------------------------------------------------------------------

    def challenge(self, d: MatchPlayer, c: MatchPlayer) -> MatchPlayer | Restart | None:
        """Defender ``d`` tackles carrier ``c``. ``None`` means the carrier rode it."""
        point = c.pos
        if not self.can_reach(d, point, 0.6):
            return None
        side = c.side
        dribble = (
            c.info.attributes.pace + c.info.attributes.acceleration + c.info.attributes.passing
        ) / 3
        win = _clamp(0.50 + 0.006 * (d.info.attributes.tackling - dribble), 0.25, 0.8)
        disc = d.info.attributes.discipline
        foul_p = 0.12 + 0.18 * (1 - disc / 99) + 0.06 * (1 - d.info.attributes.tackling / 99)
        red_beat = self.beat_for("red", d.side)
        if red_beat and (red_beat.shirt is None or red_beat.shirt == d.info.shirt):
            foul_p = 1.0
        self.move(self.tick + 4, pins={d.pid: point, c.pid: point})
        self.ball_segments.append(
            BallSegment(self.tick - 4, self.tick, "held", point, point, c.pid)
        )
        roll = self.rng.random()
        if roll < foul_p:
            severity = self.rng.random() ** 0.8
            if red_beat:
                severity = 0.99
            return self.foul(d, c, severity, reason="tackle")
        if self.rng.random() < win:
            self.emit("tackle", d.side, d, point, outcome="won", related=c)
            self.new_possession(d.side)
            if self.rng.random() < 0.3:
                # Poked away: a team-mate collects it.
                mate = self.nearest(self.teams[d.side], point, exclude=d)
                return self.complete_pass(d, mate, mate.pos, "pass", {"pass_type": "ground"})
            return self.receive(d)
        self.emit("tackle", d.side, d, point, outcome="lost", related=c)
        b = self.att(side, c.pos)
        ahead = self.pitch(
            side, _on_pitch((b[0] + self.rng.uniform(3, 6), b[1] + self.rng.uniform(-2, 2)), 1.0)
        )
        return self.carry(c, ahead)

    def foul(self, d: MatchPlayer, c: MatchPlayer, severity: float, reason: str) -> Restart:
        point = c.pos
        self.close_pressure()
        if d.yellow:
            severity *= 0.7  # already booked: more careful
        self.emit(
            "foul",
            d.side,
            d,
            point,
            related=c,
            q={"severity": round(severity, 2), "reason": reason},
        )
        setup = self.rng.uniform(26, 46)
        # Cards: severity against the defender's discipline; a yellow already shown counts.
        disc = d.info.attributes.discipline
        card: str | None = None
        red_beat = self.beat_for("red", d.side)
        yellow_beat = self.beat_for("yellow", d.side)
        if red_beat and severity > 0.95:
            card = "red"
            self.beats.pop(0)
        elif yellow_beat:
            card = "second_yellow" if d.yellow else "yellow"
            self.beats.pop(0)
        elif severity > 0.996 - 0.006 * (1 - disc / 99):
            card = "red"
        elif severity > 0.68 - 0.10 * (1 - disc / 99) - (0.0 if reason == "tackle" else -0.12):
            card = "second_yellow" if d.yellow else "yellow"
        if card in ("red", "second_yellow") and red_beat and severity <= 0.95:
            self.beats.pop(0)  # a natural dismissal is the scripted one
        elif card in ("red", "second_yellow") and not (red_beat or yellow_beat):
            # A storyline decides who is sent off: no unscripted dismissals in strict mode,
            # none before a scripted one, and never a player the script still needs.
            strict = self.storyline is not None and self.storyline.strict
            if (
                strict
                or self.pending_red(d.side)
                or d.info.shirt in self.protected(self.teams[d.side])
            ):
                card = None
        if card is not None:
            self.still(self.rng.uniform(15, 30), point)
            reasons = {
                "yellow": "reckless_tackle",
                "second_yellow": "second_booking",
                "red": "serious_foul_play",
            }
            self.emit("card", d.side, d, point, outcome=card, q={"reason": reasons[card]})
            self.cards_shown += 1
            if card == "yellow":
                d.yellow = True
            else:
                self.send_off(d)
            setup = self.rng.uniform(8, 16)
        att = self.att(c.side, point)
        if m.in_box(*att):
            return Restart("penalty", c.side, point, self.rng.uniform(40, 70))
        return Restart("free_kick", c.side, point, setup)

    def send_off(self, p: MatchPlayer) -> None:
        team = self.teams[p.side]
        touchline = (PITCH_LENGTH_M / 2, 0.5)
        self.move(self.tick + ticks(15), pins={p.pid: self.reach_point(p, touchline, 15)})
        p.sent_off = True
        p.t_off = self.tick
        team.on.remove(p)

    # ------------------------------------------------------------------------------
    # Shots, saves and goals
    # ------------------------------------------------------------------------------

    def shot(
        self, s: MatchPlayer, header: bool = False, penalty: bool = False, free_kick: bool = False
    ) -> MatchPlayer | Restart:
        side = s.side
        start = s.pos
        b = self.att(side, start)
        opps = self.opponents(side)
        gap = min(_dist(o.pos, start) for o in opps if o.group != "GK") if len(opps) > 1 else 10.0
        pressure = 0.0 if penalty or free_kick else m.pressure_from_distance(gap)
        xg = (
            0.78
            if penalty
            else m.expected_goals(b[0], b[1], pressure, header, self.blockers(side, b))
        )
        if free_kick:
            xg = min(xg, 0.07)
        keeper = self.keeper(self.teams[1 - side])
        fin = s.info.attributes.finishing
        keep = keeper.info.attributes.keeping if keeper.group == "GK" else 20
        p_goal = xg * (0.60 + 0.55 * fin / 99) * (1.30 - 0.55 * keep / 99)
        p_goal *= self.edge(side, 2.0)
        if penalty:
            p_goal = _clamp(0.62 + 0.25 * fin / 99 - 0.12 * keep / 99, 0.6, 0.88)
        goal_beat = self.beat_for("goal", side)
        forced = (
            goal_beat is not None
            and (
                goal_beat.shirt is None
                or goal_beat.shirt == s.info.shirt
                or self.beat_player(goal_beat, side) is None
            )
            and xg >= self.scripted_xg()
        )
        body = "head" if header else ("left_foot" if s.info.foot == "left" else "right_foot")
        if s.info.foot == "both" and not header:
            body = self.rng.choice(["left_foot", "right_foot"])
        power = 60 + 0.45 * fin + self.rng.uniform(-10, 14)
        shot_kmh = round(_clamp(power if not header else power * 0.55, 35, 125), 1)
        roll = self.rng.random()
        strict = self.storyline is not None and self.storyline.strict
        if forced or (roll < p_goal and not strict):
            outcome = "goal"
        else:
            rest = self.rng.random()
            block_p = 0.0 if penalty else 0.12 + 0.22 * pressure + (0.06 if b[0] < 88 else 0.0)
            if rest < block_p:
                outcome = "blocked"
            elif rest < block_p + (1 - block_p) * (0.33 + 0.10 * fin / 99):
                outcome = "saved"
            elif rest < block_p + (1 - block_p) * 0.95:
                outcome = "off_target"
            else:
                outcome = "post"
        goal_y = 34 + self.rng.uniform(-3.4, 3.4)
        if outcome in ("off_target",):
            goal_y = 34 + self.rng.choice([-1, 1]) * self.rng.uniform(4.0, 9.0)
        if outcome == "post":
            goal_y = 34 + self.rng.choice([-1, 1]) * 3.66
        end_att = (105.0, goal_y)
        end_h = round(
            self.rng.uniform(0.1, 2.3) if outcome != "off_target" else self.rng.uniform(0.2, 4.5), 2
        )
        blocker: MatchPlayer | None = None
        if outcome == "blocked":
            blocker = min(
                (o for o in opps if o.group != "GK"),
                key=lambda o: _dist(o.pos, start),
                default=keeper,
            )
            end_att = self.att(side, blocker.pos)
        speed = shot_kmh / 3.6
        dist = _dist(b, end_att)
        secs = max(0.2, dist / speed)
        q: dict[str, Any] = {
            "xg": round(xg, 3),
            "shot_speed_kmh": shot_kmh,
            "body_part": body,
            "distance_m": round(m.goal_distance(*b), 1),
            "pressure_on_passer": round(pressure, 2),
            "end_height_m": end_h if outcome != "blocked" else None,
            "big_chance": xg >= 0.30 or penalty,
            "penalty": True if penalty else None,
            "free_kick": True if free_kick else None,
        }
        end = self.pitch(side, end_att)
        t0 = self.tick
        ball_end = end
        save_pt = end
        dive = self.reach_point(keeper, self.pitch(side, (104.0, goal_y)), secs + 0.3)
        if outcome == "saved":
            # The ball ends in the keeper's hands, wherever they got to.
            save_pt = dive
            ball_end = save_pt
        height = end_h if outcome not in ("blocked", "saved") else min(end_h, 1.8)
        self.ball_segments.append(
            BallSegment(t0, t0 + ticks(secs), "shot", start, ball_end, None, height)
        )
        self.emit("shot", side, s, start, end, outcome, q=q)
        self.close_pressure()
        # The keeper goes for it: all the way for a save, most of the way when beaten.
        reach = 0.65 if outcome == "goal" else 0.35 if outcome == "off_target" else 1.0
        dive_pin = (
            keeper.x + (dive[0] - keeper.x) * reach,
            keeper.y + (dive[1] - keeper.y) * reach,
        )
        if outcome == "goal":
            if goal_beat is not None and forced:
                self.beats.pop(0)
            self.move(t0 + ticks(secs), pins={s.pid: s.pos, keeper.pid: dive_pin})
            self.ball = end
            return self.goal(s, t0)
        if outcome == "saved":
            catch = self.rng.random() < (0.35 + 0.35 * keep / 99) * (0.6 if shot_kmh > 95 else 1.0)
            self.move(t0 + ticks(secs), pins={keeper.pid: save_pt})
            self.ball = keeper.pos
            self.new_possession(1 - side)
            save_q = {"xg_faced": round(xg, 3)}
            if not catch and self.rng.random() < 0.45:
                # Tipped round the post or over the bar.
                return self.deflect_out(keeper, "save", save_q, outcome="parried", related=s)
            self.emit(
                "save",
                1 - side,
                keeper,
                keeper.pos,
                outcome="caught" if catch else "parried",
                related=s,
                q=save_q,
            )
            if catch:
                return self.keeper_has_ball(keeper)
            return self.loose_ball(
                side, (self.rng.uniform(92, 104), 34 + self.rng.uniform(-14, 14))
            )
        if outcome == "blocked":
            self.move(t0 + ticks(secs), pins={keeper.pid: dive_pin})
            self.ball = end
            if blocker is not None and self.rng.random() < 0.5:
                # Deflected behind off the blocker.
                return self.deflect_out(blocker, "interception", {"block": True})
            return self.loose_ball(side, self.att(side, end))
        if outcome == "post":
            self.move(t0 + ticks(secs), pins={keeper.pid: dive_pin})
            self.ball = end
            return self.loose_ball(
                side, (self.rng.uniform(94, 103), 34 + self.rng.uniform(-10, 10))
            )
        self.move(t0 + ticks(secs), pins={keeper.pid: dive_pin})
        self.move(self.tick + ticks(0.6))
        self.ball = self.pitch(side, (105.0, goal_y))
        return Restart(
            "goal_kick", 1 - side, self.pitch(1 - side, (5.5, 34)), self.rng.uniform(22, 38)
        )

    def loose_ball(self, attacking: int, where_att: Pt) -> MatchPlayer | Restart:
        """After a block, parry or post: whoever reaches the loose ball first."""
        spot = self.pitch(attacking, _on_pitch(where_att, 1.5))
        everyone = [p for t in self.teams for p in t.on]
        weights = [
            1.0 / (1.0 + _dist(p.pos, spot)) ** 2 * (0.8 if p.side == attacking else 1.2)
            for p in everyone
        ]
        winner = self.rng.choices(everyone, weights)[0]
        point = self.reach_point(winner, spot, 1.2)
        # The ball runs loose at a believable pace, however far it has to go.
        secs = max(1.2, _dist(self.ball, point) / 12.0)
        point = self.reach_point(winner, point, secs)
        t0 = self.tick
        self.ball_segments.append(
            BallSegment(t0, t0 + ticks(secs), "flight", self.ball, point, None, 1.0)
        )
        self.move(t0 + ticks(secs), pins={winner.pid: point})
        self.ball = point
        self.new_possession(winner.side)
        if winner.side != attacking:
            self.emit("interception", winner.side, winner, point, q={"loose_ball": True})
            if self.att(winner.side, point)[0] < 25 and self.rng.random() < 0.6:
                return self.clearance(winner)
        return self.receive(winner)

    def keeper_has_ball(self, k: MatchPlayer) -> MatchPlayer | Restart:
        self.new_possession(k.side)
        hold_s = self.rng.uniform(3, 8)
        self.hold(
            k,
            hold_s,
            drift=self.pitch(k.side, (self.rng.uniform(10, 16), self.rng.uniform(22, 46))),
        )
        if self.rng.random() < 0.55:
            return self.long_ball(k, "pass")
        mate, end = self.short_option(k, max_dist=35)
        return self.play_pass(k, mate, end, "ground", 0.0)

    def goal(self, s: MatchPlayer, shot_tick: int) -> Restart:
        """Score, celebrate, and set up the kick-off. The goal event shares the shot's time."""
        side = s.side
        self.score[side] += 1
        assist = None
        if self.last_pass and self.last_pass[1] == s.pid:
            assist = self.last_pass[0]
        q = {"assist_player_id": assist, "score_home": self.score[0], "score_away": self.score[1]}
        self.emit("goal", side, s, s.pos, self.ball, q=q, tick=shot_tick)
        # Celebration: the scorer runs to a corner flag, team-mates follow.
        flag = self.pitch(side, (103.0, 2.0 if self.att(side, s.pos)[1] < 34 else 66.0))
        celebrate = self.rng.uniform(22, 30)
        pins = {s.pid: self.reach_point(s, flag, celebrate)}
        targets = {
            p.pid: (flag[0] + self.rng.uniform(-6, 6), flag[1] + self.rng.uniform(-5, 5))
            for p in self.teams[side].on
            if p is not s and p.group != "GK"
        }
        net = self.ball
        self.still(celebrate, net, pins=pins, targets=targets, pace=0.45)
        self.still(self.rng.uniform(20, 32), net, kick_off=True, pace=0.35)
        return Restart(
            "kick_off", 1 - side, (PITCH_LENGTH_M / 2, PITCH_WIDTH_M / 2), self.rng.uniform(4, 8)
        )

    def restart_for(self, out_pt: Pt, last_touch: int) -> Restart:
        """The restart for a ball that has left the pitch at ``out_pt`` (pitch frame).

        Decided only by where the ball crossed and who touched it last, as the Laws
        say: over a goal line off the defending side is a corner, off the attacking
        side a goal kick; over a touchline it is a throw-in to the other side there.
        """
        x, y = out_pt
        if x <= 0.5 or x >= PITCH_LENGTH_M - 0.5:
            # Whose goal line is it? The side whose own goal line (x = 0) it is.
            owner = 0 if self.att(0, out_pt)[0] < PITCH_LENGTH_M / 2 else 1
            if last_touch == owner:
                flag = (0.5 if x <= 0.5 else PITCH_LENGTH_M - 0.5, 0.5 if y < 34 else 67.5)
                return Restart("corner", 1 - owner, flag, self.rng.uniform(28, 45))
            return Restart(
                "goal_kick", owner, self.pitch(owner, (5.5, 34)), self.rng.uniform(22, 38)
            )
        spot = (_clamp(x, 1.0, PITCH_LENGTH_M - 1.0), 0.0 if y < 34 else PITCH_WIDTH_M)
        return Restart("throw_in", 1 - last_touch, spot, self.rng.uniform(14, 30))

    def deflect_out(
        self,
        p: MatchPlayer,
        etype: str,
        q: dict[str, Any] | None = None,
        outcome: str | None = None,
        related: MatchPlayer | None = None,
    ) -> Restart:
        """``p`` (a defender or keeper near his own goal) sends the ball behind his own
        goal line: a header behind, a block or a save tipped round the post. The ball
        flies there visibly before the corner is given."""
        side = p.side
        here = self.att(side, p.pos)
        wide = self.rng.uniform(4.5, 14.0)
        y = 34.0 - wide if here[1] < 34 else 34.0 + wide
        if self.rng.random() < 0.25 and abs(here[1] - 34.0) < 10:
            y = 34.0 + self.rng.uniform(-3.0, 3.0)  # over the bar
        out_att = (0.0, _clamp(y, 1.0, 67.0))
        out_pt = self.pitch(side, out_att)
        d = _dist(self.ball, out_pt)
        secs = max(0.5, d / self.rng.uniform(9.0, 15.0))
        self.emit(
            etype,
            side,
            p,
            p.pos,
            out_pt,
            outcome=outcome,
            related=related,
            q={**(q or {}), "out_of_play": True},
        )
        arrive = self.flight(out_pt, secs, peak=self.rng.uniform(1.0, 3.5))
        self.move(arrive)
        self.ball = out_pt
        return self.restart_for(out_pt, side)


def _beat_period(beat: Beat) -> int:
    return 1 if beat.minute < 46 else 2


def _round_pt(p: Pt) -> list[float]:
    return [round(_clamp(p[0], 0.0, PITCH_LENGTH_M), 2), round(_clamp(p[1], 0.0, PITCH_WIDTH_M), 2)]
