"""The specialists. Each looks at one moment from one angle and returns findings with numbers.

Every number comes from the public tables; the specialists never guess. A finding is a plain dict so
it can be shared between agents as-is:

    {agent, claim, team, player?, metric, label, unit, before, after, effect_sd, evidence}

`before` is the baseline Tristan chose: the whole match so far, up to the anchor (the shift itself
is excluded). `after` is from the anchor to now.
"""

from __future__ import annotations

import math
from typing import Any

from .calibrate import load_calibration
from .match import MatchData
from .metrics import BY_KEY, METRICS, change
from .watcher import Moment

Finding = dict[str, Any]

PLAYER_STATS = [
    # key, label, unit, per (minutes), floor rate per minute
    ("duels", "Duels", "per 10 min", 10, 0.05),
    ("duels_won", "Duels won", "per 10 min", 10, 0.04),
    ("defensive_actions", "Defensive actions", "per 10 min", 10, 0.04),
    ("touches", "Touches", "per 10 min", 10, 0.2),
    ("progressive_passes", "Progressive passes", "per 10 min", 10, 0.03),
    ("sprints", "Sprints", "per 10 min", 10, 0.05),
    ("distance_m", "Distance", "m per min", 1, 0),
]
MIN_PLAYER_MINUTES = 8
CALIBRATION = load_calibration()
DISTANCE_SD = 12.0  # metres per minute: typical minute-to-minute spread of one player's running


def baseline(m: Moment) -> list[tuple[int, int]]:
    return [(0, m.anchor_m)]


def team_play(md: MatchData, m: Moment) -> list[Finding]:
    """How each team's play changed since the anchor, against its own match so far.

    `effect_sd` is the change in calibrated standard deviations. `style_sd` is what is left once the
    part explained by the team's change in territory is taken out (see calibrate.py): a style claim
    needs that, not just a big raw change.
    """
    out: list[Finding] = []
    for t in md.teams:
        tilt = change(md, BY_KEY["field_tilt"], t, m.start, m.now, baseline(m))
        z_tilt = tilt.effect_sd if tilt else 0.0
        for metric in METRICS:
            c = change(md, metric, t, m.start, m.now, baseline(m))
            if c is None:
                continue
            cal = CALIBRATION.get(metric.key, {"beta": 0.0, "resid_sd": 1.0, "raw_sd": 1.0})
            f = {"agent": "team_play", "claim": "team_change", **c.as_dict(), "polarity": c.polarity, "family": c.family}
            f["effect_sd"] = round(c.effect_sd / cal["raw_sd"], 2)
            f["style_sd"] = round((c.effect_sd - cal["beta"] * z_tilt) / cal["resid_sd"], 2)
            f["minutes"] = m.now - m.start
            out.append(f)
    return sorted(out, key=lambda f: -abs(f["effect_sd"]))


def _rate_z(a: float, la: int, b: float, lb: int, floor: float) -> float:
    """Poisson-style z-score for a per-minute rate a/la against b/lb."""
    ra, rb = a / la, b / lb
    var = max(rb, floor) * (1 / la + 1 / lb)
    return (ra - rb) / math.sqrt(var) if var > 0 else 0.0


def _distance_z(md: MatchData, pid: str, lo: int, hi: int, b_lo: int, b_hi: int) -> float:
    vals = [md.player[pid][x].get("distance_m", 0.0) for x in range(b_lo, b_hi) if x in md.player[pid]]
    if len(vals) < MIN_PLAYER_MINUTES:
        return 0.0
    mean = sum(vals) / len(vals)
    sd = max(math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)), 4.0)
    after = md.player_total(pid, lo, hi, "distance_m") / max(md.player_minutes(pid, lo, hi), 1)
    return (after - mean) / (sd / math.sqrt(max(md.player_minutes(pid, lo, hi), 1)))


def players(md: MatchData, m: Moment, top: int = 3) -> list[Finding]:
    """Players whose own output changed most since the anchor, against their own match so far."""
    out: list[Finding] = []
    for pid, team in md.player_team.items():
        la = md.player_minutes(pid, m.start, m.now)
        lb = md.player_minutes(pid, 0, m.anchor_m)
        if la < 6 or lb < MIN_PLAYER_MINUTES or md.roles.get(pid) == "GK":
            continue
        for key, label, unit, per, floor in PLAYER_STATS:
            a, b = md.player_total(pid, m.start, m.now, key), md.player_total(pid, 0, m.anchor_m, key)
            if key == "distance_m":
                z = _distance_z(md, pid, m.start, m.now, 0, m.anchor_m)
            else:
                if a + b < 3 or (a < 3 and a / la > b / lb):  # a rise needs at least three to show
                    continue
                z = _rate_z(a, la, b, lb, floor)
            out.append(
                {
                    "agent": "players",
                    "claim": "player_change",
                    "team": team,
                    "player": pid,
                    "name": md.names[pid],
                    "metric": key,
                    "label": label,
                    "unit": unit,
                    "before": round(per * b / lb, 2),
                    "after": round(per * a / la, 2),
                    "effect_sd": round(z, 2),
                    "minutes": la,
                }
            )
    out.sort(key=lambda f: -abs(f["effect_sd"]))
    by_team: dict[str, list[Finding]] = {}
    for f in out:
        if len(by_team.setdefault(f["team"], [])) < top and abs(f["effect_sd"]) >= 2:
            by_team[f["team"]].append(f)
    fades = _fatigue(md, m)
    return [f for t in md.teams for f in by_team.get(t, [])] + fades


def _fatigue(md: MatchData, m: Moment) -> list[Finding]:
    """A team-wide fade: running and sprints both down among players who started, late in the match."""
    out: list[Finding] = []
    if m.now < 55:
        return out
    for t in md.teams:
        starters = [
            pid
            for pid, team in md.player_team.items()
            if team == t
            and md.roles.get(pid) != "GK"
            and md.player_minutes(pid, 0, 5) == 5
            and md.player_minutes(pid, m.start, m.now) >= 4
        ]
        if len(starters) < 6:
            continue
        lo = max(m.start, m.now - 15)
        before = [md.player_total(p, 10, 40, "sprints") / max(md.player_minutes(p, 10, 40), 1) for p in starters]
        after = [md.player_total(p, lo, m.now, "sprints") / max(md.player_minutes(p, lo, m.now), 1) for p in starters]
        dist_b = [md.player_total(p, 10, 40, "distance_m") / max(md.player_minutes(p, 10, 40), 1) for p in starters]
        dist_a = [md.player_total(p, lo, m.now, "distance_m") / max(md.player_minutes(p, lo, m.now), 1) for p in starters]
        sb, sa = sum(before) / len(before), sum(after) / len(after)
        db, da = sum(dist_b) / len(dist_b), sum(dist_a) / len(dist_a)
        if sb > 0 and sa / sb <= 0.8 and da / db <= 0.97:
            out.append(
                {
                    "agent": "players",
                    "claim": "fatigue",
                    "team": t,
                    "metric": "sprints",
                    "label": "Sprints per player",
                    "unit": "per 10 min",
                    "before": round(10 * sb, 2),
                    "after": round(10 * sa, 2),
                    "effect_sd": round(-(1 - sa / sb) * 5, 2),
                    "players": len(starters),
                    "minutes": m.now - lo,
                }
            )
    return out


def substitutions(md: MatchData, m: Moment) -> list[Finding]:
    """Each substitute since just before the anchor against the player he replaced."""
    out: list[Finding] = []
    subs = [k for k in md.key_events if k.kind == "substitution" and m.anchor_m - 3 <= k.m < m.now]
    for k in subs:
        on, off = k.player_id, k.player_off_id
        if not on or not off:
            continue
        la = md.player_minutes(on, k.m, m.now)
        lb = md.player_minutes(off, 0, k.m)
        if la < 4 or lb < MIN_PLAYER_MINUTES:
            continue
        lb_lo = max(0, k.m - 30)  # compare with how the replaced player was going lately
        lb = md.player_minutes(off, lb_lo, k.m)
        best: Finding | None = None
        for key, label, unit, per, floor in PLAYER_STATS:
            a, b = md.player_total(on, k.m, m.now, key), md.player_total(off, lb_lo, k.m, key)
            if key == "distance_m":
                if a == 0 or b == 0:
                    continue
                z = (a / la - b / lb) / (DISTANCE_SD / math.sqrt(la))
            elif a + b < 3:
                continue
            else:
                z = _rate_z(a, la, b, lb, floor)
            f = {
                "agent": "substitutions",
                "claim": "sub_vs_replaced",
                "team": k.team_id,
                "player": on,
                "name": md.names[on],
                "replaced": off,
                "replaced_name": md.names[off],
                "metric": key,
                "label": label,
                "unit": unit,
                "before": round(per * b / lb, 2),
                "after": round(per * a / la, 2),
                "effect_sd": round(z, 2),
                "evidence": [k.event_id],
                "minute": k.m,
                "minutes": la,
            }
            if best is None or abs(z) > abs(best["effect_sd"]):
                best = f
        if best is not None:
            if abs(best["effect_sd"]) < 2:
                best["claim"] = "sub_no_difference"  # willing to say "not me"
            out.append(best)
    return out


def match_events(md: MatchData, m: Moment) -> list[Finding]:
    """Score, cards and game state around the moment."""
    out: list[Finding] = []
    start, now = md.score_at(m.anchor_m), md.score_at(m.now)
    for k in md.key_events:
        if not (m.anchor_m - 5 <= k.m < m.now) or k.kind not in ("goal", "red_card"):
            continue
        out.append(
            {
                "agent": "match_events",
                "claim": k.kind,
                "team": k.team_id,
                "player": k.player_id,
                "name": md.names.get(k.player_id or "", ""),
                "minute": k.m,
                "clock": k.clock,
                "evidence": [k.event_id],
            }
        )
    for t in md.teams:
        gd = now[t] - now[md.opp(t)]
        out.append(
            {
                "agent": "match_events",
                "claim": "game_state",
                "team": t,
                "state": "losing" if gd < 0 else "winning" if gd > 0 else "level",
                "goal_diff": gd,
                "goal_diff_at_anchor": start[t] - start[md.opp(t)],
                "players_on": int(md.team[t][min(m.now, md.last_minute)]["players_on"]),
            }
        )
    return out


SPECIALISTS = {
    "team_play": team_play,
    "players": players,
    "substitutions": substitutions,
    "match_events": match_events,
}


def investigate(md: MatchData, m: Moment) -> dict[str, list[Finding]]:
    """Run every specialist on one moment. Independent, so they could run in parallel."""
    return {name: fn(md, m) for name, fn in SPECIALISTS.items()}
