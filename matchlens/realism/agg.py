"""Turn either real (Wyscout) or synthetic matches into one per-minute shape, so both are measured
by exactly the same code.

Coordinates are 0-100 along the pitch in the acting team's attacking frame. Minutes are bucketed the
same way for both sources: first half 0-44 (stoppage time folded into 44), second half 45-94.
"""

from __future__ import annotations

import collections
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Counts = collections.defaultdict[str, float]
EMPTY: Counts = collections.defaultdict(float)
OPEN_PLAY_PASSES = {"short", "high", "header", "cross", "long", "through", "throw"}


@dataclass
class MatchAgg:
    match_id: str
    teams: list[str]  # [home, away]
    subs: list[tuple[str, int, str, str]] = field(default_factory=list)  # team, minute, on, off
    goals: list[tuple[int, str]] = field(default_factory=list)  # minute, scoring team
    reds: list[tuple[int, str]] = field(default_factory=list)  # minute, team
    team: dict[tuple[str, int], Counts] = field(default_factory=dict)  # (team, minute) -> counts
    player: dict[tuple[str, int], Counts] = field(default_factory=dict)  # (player, minute) -> counts

    def w(self, team: str, a: int, b: int, k: str) -> float:
        return sum(self.team.get((team, m), EMPTY).get(k, 0) for m in range(max(a, 0), b))

    def opp(self, team: str) -> str:
        return self.teams[1] if team == self.teams[0] else self.teams[0]


def bucket(period: int, sec: float) -> int:
    m = int(sec // 60)
    return min(m, 44) if period == 1 else 45 + min(m, 49)


def _add(
    agg: MatchAgg,
    team: str,
    player: Any,
    mn: int,
    x: float,
    kind: str,
    accurate: bool = False,
    won: bool = False,
    defending: bool = False,
    prog: float = 0.0,
    ex: float | None = None,
) -> None:
    c = agg.team.setdefault((team, mn), collections.defaultdict(float))
    pc = (
        agg.player.setdefault((str(player), mn), collections.defaultdict(float))
        if player is not None
        else collections.defaultdict(float)
    )
    c["events"] += 1
    pc["events"] += 1
    c["x_sum"] += x
    if x >= 200 / 3:
        c["ft_events"] += 1
    if kind == "pass":
        c["passes"] += 1
        pc["passes"] += 1
        if accurate:
            c["acc"] += 1
            pc["acc"] += 1
        if x >= 200 / 3:
            c["ft_passes"] += 1
        if x < 50:
            c["own_half_passes"] += 1
        if ex is not None:
            c["prog_m"] += max(0.0, ex - x) * 1.05
    elif kind == "duel":
        c["duels"] += 1
        pc["duels"] += 1
        if won:
            c["duels_won"] += 1
            pc["duels_won"] += 1
        if defending:
            c["def_duels"] += 1
            c["def_x"] += x
            pc["def_duels"] += 1
    elif kind == "shot":
        c["shots"] += 1
        pc["shots"] += 1
    elif kind == "foul":
        c["fouls"] += 1


def from_wyscout(src: Path) -> list[MatchAgg]:
    events = json.loads((src / "events_England.json").read_text())
    matches = json.loads((src / "matches_England.json").read_text())
    out: dict[int, MatchAgg] = {}
    for m in matches:
        side = {td["side"]: int(t) for t, td in m["teamsData"].items()}
        agg = MatchAgg(str(m["wyId"]), [str(side["home"]), str(side["away"])])
        for t, td in m["teamsData"].items():
            for s in td["formation"].get("substitutions") or []:
                if isinstance(s, dict):
                    agg.subs.append((str(t), int(s["minute"]), str(s["playerIn"]), str(s["playerOut"])))
        out[m["wyId"]] = agg
    for e in events:
        if e["matchPeriod"] not in ("1H", "2H"):
            continue
        agg = out[e["matchId"]]
        mn = bucket(1 if e["matchPeriod"] == "1H" else 2, e["eventSec"])
        team = str(e["teamId"])
        tags = {t["id"] for t in e["tags"]}
        pos = e["positions"]
        x = pos[0]["x"] if pos else 50
        ex = pos[1]["x"] if len(pos) > 1 else None
        name = e["eventName"]
        if name == "Pass":
            _add(agg, team, e["playerId"], mn, x, "pass", accurate=1801 in tags, ex=ex)
        elif name == "Duel":
            _add(agg, team, e["playerId"], mn, x, "duel", won=703 in tags, defending=e["subEventName"] == "Ground defending duel")
        elif name == "Shot":
            _add(agg, team, e["playerId"], mn, x, "shot")
            if 101 in tags:
                agg.goals.append((mn, team))
        elif name == "Foul":
            _add(agg, team, e["playerId"], mn, x, "foul")
            if 1701 in tags or 1703 in tags:
                agg.reds.append((mn, team))
        else:
            if name == "Free Kick" and 101 in tags:
                agg.goals.append((mn, team))
            _add(agg, team, e["playerId"], mn, x, "other")
        if 102 in tags:
            agg.goals.append((mn, agg.opp(team)))
    return list(out.values())


def from_events(match_id: str, home: str, away: str, events: list[dict[str, Any]]) -> MatchAgg:
    """Our own event format (pitch metres, acting team's frame)."""
    agg = MatchAgg(match_id, [home, away])
    for e in events:
        if e["type"] in ("stoppage",) and e.get("marker"):
            continue
        mn = bucket(e["period"], e["t"])
        team = e["team_id"]
        x = e["x"] / 1.05
        ex = e["end_x"] / 1.05
        kind = e["type"]
        if kind == "substitution":
            agg.subs.append((team, mn, e["player_id"], e["player_off_id"]))
            continue
        if kind == "pass":
            if e["subtype"] in OPEN_PLAY_PASSES:
                _add(agg, team, e["player_id"], mn, x, "pass", accurate=e["outcome"] == "complete", ex=ex)
            else:
                _add(agg, team, e["player_id"], mn, x, "other")
        elif kind == "duel":
            _add(agg, team, e["player_id"], mn, x, "duel", won=e["outcome"] == "won", defending=e.get("duel_role") == "defending")
        elif kind == "shot":
            _add(agg, team, e["player_id"], mn, x, "shot" if e["subtype"] == "open_play" else "other")
        elif kind == "foul":
            _add(agg, team, e["player_id"], mn, x, "foul")
            if e.get("card") in ("red", "second_yellow"):
                agg.reds.append((mn, team))
        else:
            _add(agg, team, e.get("player_id"), mn, x, "other")
        if kind == "shot" and e["outcome"] == "goal":
            agg.goals.append((mn, team))
    return agg
