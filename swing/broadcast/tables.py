"""Club and player stats for the screen's stats panel, as running totals minute by minute.

The panel shows whatever the match has reached on the clock, so each stat is a list with one value
per match minute: the total (or rate) over the match up to the end of that minute.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..explain.match import MatchData

Cum = dict[str, list[float]]
Value = Callable[[Cum, Cum, int], float]  # (this side's running totals, the other side's, minute) -> value


def _at(c: Cum, k: str, m: int) -> float:
    return c[k][m] if k in c else 0.0


def _count(k: str, scale: float = 1.0, nd: int = 0) -> Value:
    return lambda a, b, m: round(_at(a, k, m) * scale, nd)


def _pct(num: str, den: str) -> Value:
    return lambda a, b, m: round(100 * _at(a, num, m) / _at(a, den, m)) if _at(a, den, m) else 0


def _share(k: str) -> Value:
    def f(a: Cum, b: Cum, m: int) -> float:
        x, y = _at(a, k, m), _at(b, k, m)
        return round(100 * x / (x + y)) if x + y else 50

    return f


# key, label, unit, value, modelled
TEAM_STATS: list[tuple[str, str, str, Value, bool]] = [
    ("goals", "Goals", "", _count("goals"), False),
    ("shots", "Shots", "", _count("shots"), False),
    ("shots_on_target", "Shots on target", "", _count("shots_on_target"), False),
    ("xg", "xG", "", _count("xg", nd=2), False),
    ("possession", "Possession", "%", _share("passes"), False),
    ("passes", "Passes", "", _count("passes"), False),
    ("pass_accuracy", "Pass accuracy", "%", _pct("passes_completed", "passes"), False),
    ("own_half_passes", "Passes in own half", "%", _pct("passes_own_half", "passes"), False),
    ("progressive_passes", "Progressive passes", "", _count("progressive_passes"), False),
    ("final_third_entries", "Final-third entries", "", _count("final_third_entries"), False),
    ("box_entries", "Box entries", "", _count("box_entries"), False),
    ("crosses", "Crosses", "", _count("crosses"), False),
    ("long_balls", "Long balls", "", _count("long_passes"), False),
    ("corners", "Corners", "", _count("corners"), False),
    ("duels_won", "Duels won", "%", _pct("duels_won", "duels"), False),
    ("aerials_won", "Aerials won", "%", _pct("aerial_won", "aerial_duels"), False),
    ("defensive_actions", "Defensive actions", "", _count("defensive_actions"), False),
    ("clearances", "Clearances", "", _count("clearances"), False),
    ("high_turnovers", "High turnovers", "", _count("high_regains"), False),
    ("fouls", "Fouls", "", _count("fouls"), False),
    ("yellow_cards", "Yellow cards", "", _count("yellow_cards"), False),
    ("offsides", "Offsides", "", _count("offsides"), False),
    ("distance", "Distance", "km", _count("distance_m", 0.001, 1), True),
    ("sprints", "Sprints", "", _count("sprints"), True),
]

PLAYER_STATS: list[tuple[str, str, str, Value, bool]] = [
    ("minutes", "Minutes", "", _count("minutes"), False),
    ("goals", "Goals", "", _count("goals"), False),
    ("shots", "Shots", "", _count("shots"), False),
    ("xg", "xG", "", _count("xg", nd=2), False),
    ("touches", "Touches", "", _count("touches"), False),
    ("passes", "Passes", "", _count("passes"), False),
    ("pass_accuracy", "Pass accuracy", "%", _pct("passes_completed", "passes"), False),
    ("progressive_passes", "Progressive passes", "", _count("progressive_passes"), False),
    ("duels", "Duels", "", _count("duels"), False),
    ("duels_won", "Duels won", "", _count("duels_won"), False),
    ("defensive_actions", "Defensive actions", "", _count("defensive_actions"), False),
    ("fouls", "Fouls", "", _count("fouls"), False),
    ("distance", "Distance", "km", _count("distance_m", 0.001, 2), True),
    ("sprints", "Sprints", "", _count("sprints"), True),
]


def _running(rows: list[dict[str, float]], n: int) -> Cum:
    keys = {k for r in rows for k in r}
    out: Cum = {k: [] for k in keys}
    for k in keys:
        s = 0.0
        for m in range(n):
            s += rows[m].get(k, 0.0) if m < len(rows) else 0.0
            out[k].append(s)
    return out


def _defs(stats: list[tuple[str, str, str, Value, bool]]) -> list[dict[str, Any]]:
    return [{"key": k, "label": label, "unit": unit, "modelled": modelled} for k, label, unit, _, modelled in stats]


def stats_tables(md: MatchData) -> dict[str, Any]:
    n = md.last_minute + 1
    cum = {t: _running(md.team[t], n) for t in md.teams}
    teams = {t: {k: [fn(cum[t], cum[md.opp(t)], m) for m in range(n)] for k, _, _, fn, _ in TEAM_STATS} for t in md.teams}
    players: list[dict[str, Any]] = []
    for pid, team in md.player_team.items():
        rows_by_m = md.player.get(pid, {})
        if not rows_by_m:
            continue
        rows = [{**rows_by_m[m], "minutes": 1.0} if m in rows_by_m else {} for m in range(n)]
        pc = _running(rows, n)
        players.append(
            {
                "id": pid,
                "name": md.names.get(pid, pid),
                "team": team,
                "role": md.roles.get(pid, ""),
                "from": min(rows_by_m),
                "stats": {k: [fn(pc, pc, m) for m in range(n)] for k, _, _, fn, _ in PLAYER_STATS},
            }
        )
    order = {"GK": 0, "DF": 1, "MF": 2, "FW": 3}
    players.sort(key=lambda p: (md.teams.index(p["team"]), p["from"] > 0, order.get(p["role"], 4), p["name"]))
    return {"team_stats": _defs(TEAM_STATS), "player_stats": _defs(PLAYER_STATS), "teams": teams, "players": players}
