"""Minute-by-minute team and player tables from a match's events.

This works for any match in the public format (docs/data-format.md), generated or not. Physical
columns come from physical.csv when the match supplies one; otherwise they are left empty.

Coordinates are pitch metres (105 x 68) in the acting team's attacking frame.
"""

from __future__ import annotations

import collections
from typing import Any

PITCH = 105.0
FINAL_THIRD = PITCH * 2 / 3
BOX_X, BOX_Y = PITCH - 16.5, (68 - 40.3) / 2
Counts = collections.defaultdict[str, float]
OPEN_PLAY = {"short", "high", "header", "cross", "long", "through", "throw"}

TEAM_COLUMNS = [
    "passes",
    "passes_completed",
    "passes_own_half",
    "passes_final_third",
    "passes_final_third_completed",
    "progressive_passes",
    "long_passes",
    "crosses",
    "final_third_entries",
    "box_entries",
    "touches",
    "touches_final_third",
    "duels",
    "duels_won",
    "aerial_duels",
    "aerial_won",
    "defensive_actions",
    "defensive_action_x_sum",
    "high_regains",
    "shots",
    "shots_on_target",
    "xg",
    "goals",
    "fouls",
    "yellow_cards",
    "red_cards",
    "corners",
    "offsides",
    "distance_m",
    "hsr_m",
    "sprints",
]
PLAYER_COLUMNS = [
    "touches",
    "passes",
    "passes_completed",
    "progressive_passes",
    "duels",
    "duels_won",
    "defensive_actions",
    "defensive_action_x_sum",
    "shots",
    "xg",
    "goals",
    "fouls",
    "distance_m",
    "hsr_m",
    "sprints",
]


def in_box(x: float, y: float) -> bool:
    return x >= BOX_X and BOX_Y <= y <= 68 - BOX_Y


def aggregate(
    meta: dict[str, Any], events: list[dict[str, Any]], physical: list[dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (team_minute rows, player_minute rows)."""
    teams = [t["team_id"] for t in meta["teams"]]
    team: dict[tuple[str, int], Counts] = collections.defaultdict(lambda: collections.defaultdict(float))
    player: dict[tuple[str, int], Counts] = collections.defaultdict(lambda: collections.defaultdict(float))
    player_team = {p["player_id"]: t["team_id"] for t in meta["teams"] for p in t["players"]}
    on_since: dict[str, int] = {p["player_id"]: 0 for t in meta["teams"] for p in t["players"] if p.get("starter")}
    off_at: dict[str, int] = {}
    last_m = 0
    clock_of: dict[int, str] = {}
    period_of: dict[int, int] = {}

    for e in events:
        m = e["m"]
        last_m = max(last_m, m)
        clock_of.setdefault(m, e["clock"].split(":")[0])
        period_of.setdefault(m, e["period"])
        t, pid = e["team_id"], e.get("player_id")
        c = team[(t, m)]
        pc: Counts = player[(pid, m)] if pid else collections.defaultdict(float)
        kind, sub, out = e["type"], e["subtype"], e["outcome"]
        x, y, ex, ey = e["x"], e["y"], e["end_x"], e["end_y"]
        if kind == "substitution" and pid:
            on_since[pid] = m
            off_at[e["player_off_id"]] = m
            continue
        if kind in ("pass", "carry", "touch", "shot", "duel", "clearance"):
            c["touches"] += 1
            pc["touches"] += 1
            if x >= FINAL_THIRD:
                c["touches_final_third"] += 1
        if kind == "pass":
            if sub == "corner":
                c["corners"] += 1
            if sub not in OPEN_PLAY:
                continue
            ok = out == "complete"
            c["passes"] += 1
            pc["passes"] += 1
            c["passes_completed"] += ok
            pc["passes_completed"] += ok
            if x < PITCH / 2:
                c["passes_own_half"] += 1
            if x >= FINAL_THIRD:
                c["passes_final_third"] += 1
                c["passes_final_third_completed"] += ok
            if sub == "long" or ((ex - x) ** 2 + (ey - y) ** 2) ** 0.5 >= 32:
                c["long_passes"] += 1
            if sub == "cross":
                c["crosses"] += 1
            if ok and ex - x >= 10 and ex > PITCH / 2:
                c["progressive_passes"] += 1
                pc["progressive_passes"] += 1
            if ok and x < FINAL_THIRD <= ex:
                c["final_third_entries"] += 1
            if ok and not in_box(x, y) and in_box(ex, ey):
                c["box_entries"] += 1
        elif kind == "carry":
            if x < FINAL_THIRD <= ex:
                c["final_third_entries"] += 1
            if not in_box(x, y) and in_box(ex, ey):
                c["box_entries"] += 1
        elif kind == "duel":
            won = out == "won"
            c["duels"] += 1
            pc["duels"] += 1
            c["duels_won"] += won
            pc["duels_won"] += won
            if sub == "aerial":
                c["aerial_duels"] += 1
                c["aerial_won"] += won
            if e.get("duel_role") == "defending" or (sub != "ground" and won):
                c["defensive_actions"] += 1
                c["defensive_action_x_sum"] += x
                pc["defensive_actions"] += 1
                pc["defensive_action_x_sum"] += x
                if won and x >= PITCH - 40:
                    c["high_regains"] += 1
        elif kind == "clearance":
            c["defensive_actions"] += 1
            c["defensive_action_x_sum"] += x
            pc["defensive_actions"] += 1
            pc["defensive_action_x_sum"] += x
        elif kind == "shot":
            c["shots"] += 1
            pc["shots"] += 1
            c["xg"] += e.get("xg", 0.0)
            pc["xg"] += e.get("xg", 0.0)
            if out in ("goal", "saved"):
                c["shots_on_target"] += 1
            if out == "goal":
                c["goals"] += 1
                pc["goals"] += 1
        elif kind == "foul":
            c["fouls"] += 1
            pc["fouls"] += 1
            c["defensive_actions"] += 1
            c["defensive_action_x_sum"] += x
            card = e.get("card")
            if card == "yellow":
                c["yellow_cards"] += 1
            elif card in ("red", "second_yellow"):
                c["red_cards"] += 1
                if pid:
                    off_at[pid] = m
        elif kind == "offside":
            c["offsides"] += 1

    for phys in physical or []:
        m, pid = int(phys["m"]), phys["player_id"]
        for k in ("distance_m", "hsr_m", "sprints"):
            v = float(phys[k])
            player[(pid, m)][k] += v
            team[(phys["team_id"], m)][k] += v

    team_rows, player_rows = [], []
    score = {t: 0 for t in teams}
    reds = {t: 0 for t in teams}
    for m in range(last_m + 1):
        snapshot = dict(score)
        for t in teams:
            c = team[(t, m)]
            o = teams[1] if t == teams[0] else teams[0]
            row: dict[str, Any] = {
                "m": m,
                "period": period_of.get(m, 1 if m < 45 else 2),
                "clock_minute": clock_of.get(m, ""),
                "team_id": t,
                "goals_for_before": snapshot[t],
                "goals_against_before": snapshot[o],
                "players_on": 11 - reds[t],
            }
            row.update(
                {
                    k: round(c.get(k, 0), 3) if k in ("xg", "distance_m", "hsr_m", "defensive_action_x_sum") else int(c.get(k, 0))
                    for k in TEAM_COLUMNS
                }
            )
            team_rows.append(row)
        for t in teams:
            score[t] += int(team[(t, m)].get("goals", 0))
            reds[t] += int(team[(t, m)].get("red_cards", 0))
        for pid, tid in player_team.items():
            if pid not in on_since or on_since[pid] > m or (pid in off_at and off_at[pid] < m):
                continue
            pc = player[(pid, m)]
            prow: dict[str, Any] = {"m": m, "team_id": tid, "player_id": pid}
            prow.update(
                {
                    k: round(pc.get(k, 0), 3)
                    if k in ("xg", "distance_m", "hsr_m", "defensive_action_x_sum")
                    else int(pc.get(k, 0))
                    for k in PLAYER_COLUMNS
                }
            )
            player_rows.append(prow)
    return team_rows, player_rows
