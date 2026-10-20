"""The Watcher: keeps the momentum scale and decides when something is worth explaining.

It reads only the public tables, minute by minute, and never looks ahead: a moment found at
minute `now` uses data from before `now` only. It raises three kinds of moment:

- **shift**: one side's share of final-third play over the last few minutes has moved a long way
  from the 15 minutes before. The anchor is the minute the change started.
- **recovery**: a shift that only takes a team back to its own level after a dip.
- **event**: a goal, red card, substitution or half-time, looked at once enough play has followed,
  whether or not momentum moved.

Nothing is raised before the settling period ends (20').
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .match import KeyEvent, MatchData
from .metrics import share

SETTLE = 20  # no moments before this minute
RECENT = 6  # minutes in the "now" window
PRIOR = 15  # minutes compared against
SWING = 25.0  # field-tilt points between the two windows that count as a shift
COOLDOWN = 10  # minutes between shifts
EVENT_WAIT = 8  # minutes of play needed after an event before it can be judged
EVENT_LINK = (-2, 6)  # a shift starting this close to an event is put down to it
DIP = 8.0  # points below a team's own level that count as a dip
PRIORITY = {"red_card": 0, "goal": 1, "half_time": 2, "substitution": 3}

tilt = share("touches_final_third", 8)


@dataclass
class Moment:
    now: int  # minute the moment can go on screen (data before this minute only)
    anchor_m: int  # the minute the change started, or the event's minute
    mode: str  # shift | recovery | event
    gainer: str | None  # team whose share of play rose (None if momentum didn't move)
    swing: float  # field-tilt points gained by `gainer` (0 when momentum didn't move)
    momentum_before: float  # home field tilt %, before the anchor
    momentum_now: float  # home field tilt %, since the anchor
    events: list[KeyEvent] = field(default_factory=list)  # the event(s) anchoring an event-mode moment

    @property
    def shifted(self) -> bool:
        return self.gainer is not None

    @property
    def start(self) -> int:
        """First minute of the "since" window. An event's own minute holds play from before it."""
        return self.anchor_m + 1 if self.events else self.anchor_m


def momentum_series(md: MatchData, decay: float = 0.8) -> list[float]:
    """Home share (%) of final-third touches, exponentially weighted. Drives the always-on scale."""
    home, away = md.teams
    h = a = 0.0
    out = []
    for m in range(md.last_minute + 1):
        h = h * decay + md.team[home][m].get("touches_final_third", 0.0)
        a = a * decay + md.team[away][m].get("touches_final_third", 0.0)
        out.append(round(100 * h / (h + a), 1) if h + a > 0 else 50.0)
    return out


def _tilt(md: MatchData, team: str, lo: int, hi: int) -> float | None:
    return tilt(md, team, max(lo, 0), hi)


def _anchor(md: MatchData, team: str, now: int) -> int:
    """The split point in the last few minutes that best separates before from after."""
    best, best_s = -1.0, now - RECENT
    for s in range(now - 10, now - 4):
        after, before = _tilt(md, team, s, now), _tilt(md, team, s - 12, s)
        if after is None or before is None:
            continue
        if (d := after - before) > best:
            best, best_s = d, s
    return best_s


def find_shifts(md: MatchData) -> list[Moment]:
    home = md.teams[0]
    out: list[Moment] = []
    last = -99
    for now in range(SETTLE, md.last_minute + 2):
        recent = _tilt(md, home, now - RECENT, now)
        prior = _tilt(md, home, now - RECENT - PRIOR, now - RECENT)
        if recent is None or prior is None or abs(recent - prior) < SWING or now - last < COOLDOWN:
            continue
        gainer = home if recent > prior else md.opp(home)
        # the latest three minutes must still lean the same way, or it was a blip
        tail = _tilt(md, gainer, now - 3, now)
        g_prior = _tilt(md, gainer, now - RECENT - PRIOR, now - RECENT)
        if tail is None or g_prior is None or tail - g_prior < SWING / 2:
            continue
        s = _anchor(md, gainer, now)
        after, before = _tilt(md, gainer, s, now), _tilt(md, gainer, s - PRIOR, s)
        if after is None or before is None:
            continue
        mode = "recovery" if _is_recovery(md, gainer, s, now) else "shift"
        h_before, h_now = _tilt(md, home, s - PRIOR, s), _tilt(md, home, s, now)
        out.append(Moment(now, s, mode, gainer, after - before, h_before or 50.0, h_now or 50.0))
        last = now
    return out


def _is_recovery(md: MatchData, team: str, s: int, now: int) -> bool:
    """The team had dipped below its own level and has come back to about where it was."""
    level = _tilt(md, team, 0, s - 12)
    if level is None or s - 12 < 8:
        return False
    dip, back = _tilt(md, team, s - 12, s), _tilt(md, team, s, now)
    if dip is None or back is None:
        return False
    return dip <= level - DIP and back <= level + DIP * 1.5


def group_events(md: MatchData) -> list[list[KeyEvent]]:
    """Key events in time order; a team's substitutions within 3 minutes count as one change."""
    groups: list[list[KeyEvent]] = []
    for k in md.key_events:
        prev = groups[-1] if groups else None
        if (
            prev
            and k.kind == "substitution"
            and prev[0].kind == "substitution"
            and prev[0].team_id == k.team_id
            and k.m - prev[0].m <= 3
        ):
            prev.append(k)
        else:
            groups.append([k])
    return groups


def watch(md: MatchData) -> list[Moment]:
    """Every moment in the match, in the order they would go on screen."""
    home = md.teams[0]
    shifts = find_shifts(md)
    groups = group_events(md)
    used: set[int] = set()
    for sh in shifts:
        lo, hi = sh.anchor_m + EVENT_LINK[0], sh.anchor_m + EVENT_LINK[1]
        near = [g for g in groups if lo <= g[0].m <= hi and g[0].m < sh.now - 4 and id(g) not in used]
        if near:
            g = min(near, key=lambda g: (PRIORITY[g[0].kind], abs(g[0].m - sh.anchor_m)))
            used.add(id(g))
            sh.events = g
            sh.mode = "event"
            sh.anchor_m = g[0].m
            sh.momentum_before = _tilt(md, home, sh.anchor_m - PRIOR, sh.anchor_m) or 50.0
            sh.momentum_now = _tilt(md, home, sh.anchor_m + 1, sh.now) or 50.0
    moments = list(shifts)
    for g in groups:
        if id(g) in used:
            continue
        e = g[0]
        now = max(e.m + EVENT_WAIT, SETTLE)
        if now > md.last_minute + 1:
            continue
        before = _tilt(md, home, e.m - PRIOR, e.m)
        after = _tilt(md, home, e.m + 1, now)
        if before is None or after is None:
            continue
        moved = abs(after - before) >= SWING
        gainer = (home if after > before else md.opp(home)) if moved else None
        moments.append(Moment(now, e.m, "event", gainer, abs(after - before) if moved else 0.0, before, after, g))
    return sorted(moments, key=lambda mo: (mo.now, mo.anchor_m))
