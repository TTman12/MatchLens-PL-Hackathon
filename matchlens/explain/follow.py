"""Follow a player: one player's match, pinned on screen from kick-off to the final whistle.

For every player the bundle carries:
- moments: name tags the screen pops up beside the player's strip, when something happens (a goal,
  an assist, a shot, a card, coming on or off) or a running total reaches a set threshold (10 km
  covered, 20 sprints, 50 passes, 10 duels won, ...), as broadcasters tag players;
- involvement: touches in each five minutes, for a sparkline of when he was in the game;
- ranks: at full time, where he finished in his team on each stat, for the recap.

Everything is counted from the public tables and events; nothing is inferred.
"""

from __future__ import annotations

from typing import Any

from .match import MatchData

BLOCK = 5  # minutes per involvement bar
# running total -> the thresholds that pop a tag (player-table keys, see broadcast/tables.py)
THRESHOLDS: dict[str, tuple[float, ...]] = {
    "distance": (5, 10),
    "sprints": (10, 20, 30),
    "passes": (25, 50, 75),
    "progressive_passes": (5, 10),
    "duels_won": (5, 10),
    "defensive_actions": (5, 10, 15),
}
RANKED = (
    "touches",
    "passes",
    "pass_accuracy",
    "progressive_passes",
    "duels_won",
    "defensive_actions",
    "distance",
    "sprints",
    "shots",
)


def _assists(md: MatchData) -> dict[int, str]:
    """Goal event index -> the team-mate whose completed pass the scorer received, in the same move."""
    out = {}
    ev = md.events
    for i, e in enumerate(ev):
        if e["type"] != "shot" or e["outcome"] != "goal":
            continue
        for p in reversed(ev[max(0, i - 6) : i]):
            if p["possession"] != e["possession"]:
                break
            if p["type"] == "pass" and p["team_id"] == e["team_id"]:
                if p.get("outcome") == "complete" and p.get("receiver_id") == e["player_id"] and p["player_id"] != e["player_id"]:
                    out[i] = p["player_id"]
                break
    return out


def moments(md: MatchData, stats: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Player id -> his tags, in time order. `m` is the match minute the tag goes up in."""
    out: dict[str, list[dict[str, Any]]] = {p["id"]: [] for p in stats["players"]}
    assists = _assists(md)
    for i, e in enumerate(md.events):
        pid = e.get("player_id")
        if pid not in out:
            continue
        if e["type"] == "shot":
            if e["outcome"] == "goal":
                out[pid].append({"m": e["m"], "kind": "goal"})
                if i in assists and assists[i] in out:
                    out[assists[i]].append({"m": e["m"], "kind": "assist"})
            else:
                xg = e.get("xg")
                out[pid].append({"m": e["m"], "kind": "shot", **({"value": f"{float(xg):.2f}"} if xg not in (None, "") else {})})
        elif e["type"] == "foul" and e.get("card"):
            out[pid].append({"m": e["m"], "kind": "red" if e["card"] in ("red", "second_yellow") else "yellow"})
    for k in md.key_events:
        if k.kind == "substitution":
            if k.player_id in out:
                out[k.player_id].append({"m": k.m, "kind": "on"})
            if k.player_off_id in out:
                out[k.player_off_id].append({"m": k.m, "kind": "off"})
    for p in stats["players"]:
        for key, marks in THRESHOLDS.items():
            series = p["stats"][key]
            for mark in marks:
                m = next((i for i, v in enumerate(series) if v >= mark), None)
                if m is not None:
                    value = f"{mark:g} km" if key == "distance" else f"{mark:g}"
                    out[p["id"]].append({"m": m, "kind": key, "value": value})
        out[p["id"]].sort(key=lambda x: x["m"])
    return out


def involvement(md: MatchData, pid: str) -> list[int]:
    """Touches in each block of BLOCK minutes, from kick-off (0 while he was off the pitch)."""
    rows = md.player.get(pid, {})
    n = md.last_minute + 1
    return [
        round(sum(rows[m].get("touches", 0) for m in range(lo, min(lo + BLOCK, n)) if m in rows)) for lo in range(0, n, BLOCK)
    ]


def ranks(stats: dict[str, Any], pid: str) -> list[dict[str, Any]]:
    """Where the player finished in his team on each stat, best first (ties share the rank)."""
    me = next(p for p in stats["players"] if p["id"] == pid)
    squad = [p for p in stats["players"] if p["team"] == me["team"] and p["role"] != "GK" and p["stats"]["minutes"][-1] > 0]
    if me not in squad:
        return []
    out = []
    for k in RANKED:
        v = me["stats"][k][-1]
        if not v:
            continue
        rank = 1 + sum(1 for q in squad if q["stats"][k][-1] > v)
        out.append({"key": k, "rank": rank, "value": v, "of": len(squad)})
    out.sort(key=lambda r: (r["rank"], RANKED.index(r["key"])))
    return out


def follow(md: MatchData, stats: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Player id -> what follow mode shows for him."""
    tags = moments(md, stats)
    return {
        p["id"]: {"moments": tags[p["id"]], "involvement": involvement(md, p["id"]), "ranks": ranks(stats, p["id"])}
        for p in stats["players"]
    }
