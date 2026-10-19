"""Build the hand-made sample match in ``data/sample/``.

The sample is three minutes of one fictional match, scripted by hand below: a goal with a
twelve-second build-up, a corner and a yellow card. It exists so the stats, agents and web
tracks can build against real-shaped data before the simulator is ready.

Everything is deterministic. Run it again after changing the storyboard or a contract:

    python scripts/make_sample_match.py

Writes ``league.json``, ``season.json``, ``match.json``, ``events.json``, ``frames.jsonl``,
``moments.json`` and ``cues.json``. Every file is validated against the contracts first.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

from matchlens.contracts import (
    FRAME_RATE_HZ,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    SCHEMA_VERSION,
    Cue,
    CueTrack,
    Frame,
    League,
    MatchEvent,
    MatchMeta,
    Moment,
    Season,
    format_clock,
)
from matchlens.contracts.pitch import Direction, attacking_direction, to_attacking

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sample"

MATCH_ID = "m017"
MATCHDAY = 9
LEAGUE_ID = "fl"
SEASON_ID = "2026"
HOME, AWAY = "ash", "brk"
HOME_DIRECTION: Direction = "+x"  # Ashmere attack toward pitch x = 105 in period 1
END_T = 180.0
BALL_RADIUS = 0.11

# ---------------------------------------------------------------------------------------
# The fictional league. Club and player names are invented; none refer to real people.
# ---------------------------------------------------------------------------------------

CLUBS: list[dict[str, Any]] = [
    {
        "team_id": "ash",
        "name": "Ashmere Athletic",
        "short_name": "Ashmere",
        "city": "Ashmere",
        "stadium": "Kilnside Park",
        "colours": {"primary": "#B3202A", "secondary": "#F2E8D5", "text": "#FFFFFF"},
        "rating": 74,
        "formation": "4-3-3",
        "rival_ids": ["brk"],
    },
    {
        "team_id": "brk",
        "name": "Brackenford",
        "short_name": "Brackenford",
        "city": "Brackenford",
        "stadium": "The Weir Ground",
        "colours": {"primary": "#1D4E89", "secondary": "#F5C518", "text": "#F5C518"},
        "rating": 71,
        "formation": "4-2-3-1",
        "rival_ids": ["ash"],
    },
    {
        "team_id": "cal",
        "name": "Calderwick Town",
        "short_name": "Calderwick",
        "city": "Calderwick",
        "stadium": "Saltmarsh Lane",
        "colours": {"primary": "#2E7D4F", "secondary": "#FFFFFF", "text": "#FFFFFF"},
        "rating": 76,
        "formation": "4-3-3",
        "rival_ids": [],
    },
    {
        "team_id": "els",
        "name": "Elsbridge Rovers",
        "short_name": "Elsbridge",
        "city": "Elsbridge",
        "stadium": "Pennant Road",
        "colours": {"primary": "#5B2A86", "secondary": "#C9C9C9", "text": "#FFFFFF"},
        "rating": 68,
        "formation": "3-5-2",
        "rival_ids": [],
    },
]

FIRST_NAMES = [
    "Tomas", "Rafe", "Idris", "Mateo", "Kofi", "Luka", "Oren", "Silas", "Jonah", "Emil",
    "Bram", "Caio", "Nico", "Yannick", "Aurel", "Dario", "Felix", "Kian", "Lior", "Marek",
    "Osei", "Pavel", "Ruben", "Soren", "Teo", "Ulrik", "Vito", "Wren", "Ezra", "Hugo",
]  # fmt: skip
SURNAMES = [
    "Varrow", "Kestley", "Ostrand", "Brennick", "Halloway", "Penthorne", "Quillan", "Dravik",
    "Morrell", "Asquend", "Fenwright", "Lathrop", "Corvane", "Ibbotsen", "Tarrance", "Wexley",
    "Ruskin-Hale", "Delvaux", "Marchetti-Rowe", "Okonedo-Finch", "Sallow", "Thistlewood",
    "Venn", "Harrowgate", "Pellow", "Strand", "Abernath", "Kiloran", "Duvessa", "Brightmoor",
]  # fmt: skip

# (shirt, position, role, slot) for each formation. Starters are shirts 1 to 11.
FORMATION_433 = [
    (1, "GK", "GK", "GK"), (2, "DF", "RB", "RB"), (4, "DF", "CB", "RCB"),
    (5, "DF", "CB", "LCB"), (3, "DF", "LB", "LB"), (6, "MF", "DM", "DM"),
    (8, "MF", "CM", "RCM"), (10, "MF", "CM", "LCM"), (7, "FW", "RW", "RW"),
    (9, "FW", "ST", "ST"), (11, "FW", "LW", "LW"),
]  # fmt: skip
FORMATION_4231 = [
    (1, "GK", "GK", "GK"), (2, "DF", "RB", "RB"), (4, "DF", "CB", "RCB"),
    (5, "DF", "CB", "LCB"), (3, "DF", "LB", "LB"), (6, "MF", "DM", "RDM"),
    (8, "MF", "DM", "LDM"), (7, "MF", "RW", "RAM"), (10, "MF", "AM", "CAM"),
    (11, "MF", "LW", "LAM"), (9, "FW", "ST", "ST"),
]  # fmt: skip
FORMATION_352 = [
    (1, "GK", "GK", "GK"), (4, "DF", "CB", "RCB"), (5, "DF", "CB", "CB"),
    (3, "DF", "CB", "LCB"), (2, "MF", "RWB", "RWB"), (6, "MF", "DM", "DM"),
    (8, "MF", "CM", "RCM"), (10, "MF", "CM", "LCM"), (11, "MF", "LWB", "LWB"),
    (9, "FW", "ST", "RS"), (7, "FW", "ST", "LS"),
]  # fmt: skip
FORMATIONS = {"4-3-3": FORMATION_433, "4-2-3-1": FORMATION_4231, "3-5-2": FORMATION_352}
BENCH = [(12, "DF", "CB"), (13, "GK", "GK"), (14, "MF", "CM"), (15, "DF", "FB"),
         (16, "MF", "AM"), (17, "FW", "W"), (18, "FW", "ST")]  # fmt: skip

# Neutral slots for a team attacking pitch +x, with the ball on the halfway line.
SLOT_XY: dict[str, tuple[float, float]] = {
    "GK": (5, 34), "RB": (27, 9), "RCB": (21, 25), "CB": (20, 34), "LCB": (21, 43),
    "LB": (27, 59), "RWB": (33, 7), "LWB": (33, 61), "DM": (33, 34), "RDM": (34, 27),
    "LDM": (34, 41), "RCM": (41, 24), "LCM": (41, 44), "RAM": (46, 10), "CAM": (45, 34),
    "LAM": (46, 58), "RW": (47, 9), "LW": (47, 59), "ST": (49, 34), "RS": (49, 29),
    "LS": (49, 39),
}  # fmt: skip

# Players whose numbers the story depends on: Ashmere's striker is quick, their left back
# is one yellow from a ban.
OVERRIDES: dict[str, dict[str, Any]] = {
    "ash-09": {"name": "Idris Varrow", "short_name": "Varrow", "top_speed_kmh": 34.6,
               "attributes": {"pace": 91, "acceleration": 89, "finishing": 84}},
    "ash-08": {"name": "Teo Kestley", "short_name": "Kestley",
               "attributes": {"passing": 88, "vision": 90}},
    "ash-06": {"name": "Osei Brennick", "short_name": "Brennick"},
    "ash-03": {"name": "Rafe Halloway", "short_name": "Halloway",
               "attributes": {"discipline": 38, "tackling": 77}},
    "ash-01": {"name": "Bram Ostrand", "short_name": "Ostrand"},
    "brk-01": {"name": "Soren Quillan", "short_name": "Quillan"},
    "brk-08": {"name": "Caio Penthorne", "short_name": "Penthorne"},
    "brk-10": {"name": "Luka Dravik", "short_name": "Dravik"},
}  # fmt: skip


def build_league(rng: random.Random) -> League:
    names = [(f, s) for f in FIRST_NAMES for s in SURNAMES]
    rng.shuffle(names)
    used = {o["name"] for o in OVERRIDES.values()}
    names = [n for n in names if f"{n[0]} {n[1]}" not in used]
    clubs = []
    for club in CLUBS:
        squad = []
        roster = [(s, p, r) for s, p, r, _ in FORMATIONS[club["formation"]]] + BENCH
        for shirt, position, role in roster:
            pid = f"{club['team_id']}-{shirt:02d}"
            first, last = names.pop()
            base = club["rating"]
            attrs = {
                key: max(20, min(95, base + rng.randint(-12, 10)))
                for key in (
                    "pace", "acceleration", "passing", "vision", "finishing",
                    "tackling", "keeping", "discipline", "stamina",
                )
            }  # fmt: skip
            attrs["keeping"] = attrs["keeping"] if position == "GK" else rng.randint(10, 25)
            player: dict[str, Any] = {
                "player_id": pid,
                "name": f"{first} {last}",
                "short_name": last,
                "shirt": shirt,
                "position": position,
                "role": role,
                "foot": rng.choice(["right", "right", "right", "left", "both"]),
                "top_speed_kmh": round(29.5 + attrs["pace"] / 99 * 5.5, 1),
                "attributes": attrs,
            }
            override = OVERRIDES.get(pid, {})
            player.update({k: v for k, v in override.items() if k != "attributes"})
            player["attributes"].update(override.get("attributes", {}))
            squad.append(player)
        clubs.append({**club, "squad": squad})
    return League.model_validate(
        {"schema_version": SCHEMA_VERSION, "league_id": LEAGUE_ID, "name": "The Fictional League",
         "clubs": clubs}
    )  # fmt: skip


# ---------------------------------------------------------------------------------------
# Season so far: a seeded Poisson results model over a double round robin, so the table
# adds up. Player stats are allocated from those results.
# ---------------------------------------------------------------------------------------

ROUND = [[("ash", "brk"), ("cal", "els")], [("ash", "cal"), ("brk", "els")],
         [("els", "ash"), ("brk", "cal")]]  # fmt: skip


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def build_season(rng: random.Random, league: League) -> Season:
    ratings = {c.team_id: c.rating for c in league.clubs}
    squads = {c.team_id: c.squad for c in league.clubs}
    schedule: list[tuple[int, str, str]] = []
    for md in range(1, 11):
        pairs = ROUND[(md - 1) % 3]
        if (md - 1) // 3 % 2 == 1:
            pairs = [(a, h) for h, a in pairs]
        schedule += [(md, h, a) for h, a in pairs]
    # Matchday 9 is the streamed match, Ashmere v Brackenford; matchday 10 sends Ashmere
    # to Calderwick, which is the fixture a suspension would hit.
    schedule = [s for s in schedule if s[0] < 9] + [
        (9, "ash", "brk"), (9, "cal", "els"), (10, "cal", "ash"), (10, "els", "brk"),
    ]  # fmt: skip

    stats: dict[str, dict[str, Any]] = {}
    for team_id, squad in squads.items():
        for p in squad:
            stats[p.player_id] = {
                "player_id": p.player_id, "team_id": team_id, "appearances": 0, "minutes": 0,
                "goals": 0, "assists": 0, "shots": 0, "passes": 0, "pass_acc": [],
                "difficulty": [], "top_speed_kmh": 0.0, "distance_km": 0.0,
                "yellow_cards": 0, "red_cards": 0, "last_goal_matchday": None,
            }  # fmt: skip
    rows: dict[str, dict[str, Any]] = {
        t: {"team_id": t, "played": 0, "won": 0, "drawn": 0, "lost": 0, "goals_for": 0,
            "goals_against": 0, "points": 0, "form": []}
        for t in ratings
    }  # fmt: skip
    fixtures = []
    goal_weight = {"FW": 6, "MF": 3, "DF": 1, "GK": 0}
    for i, (md, home, away) in enumerate(schedule, start=1):
        match_id = f"m{i:03d}"
        if md >= MATCHDAY:
            status = "live" if match_id == MATCH_ID else "scheduled"
            fixtures.append({"match_id": match_id, "matchday": md, "home_id": home,
                             "away_id": away, "status": status})  # fmt: skip
            continue
        edge = (ratings[home] - ratings[away]) / 40
        goals = {home: _poisson(rng, 1.45 + edge), away: _poisson(rng, 1.15 - edge)}
        fixtures.append({"match_id": match_id, "matchday": md, "home_id": home,
                         "away_id": away, "status": "played",
                         "score": {"home": goals[home], "away": goals[away]}})  # fmt: skip
        for team, opp in ((home, away), (away, home)):
            row = rows[team]
            row["played"] += 1
            row["goals_for"] += goals[team]
            row["goals_against"] += goals[opp]
            result = "W" if goals[team] > goals[opp] else "L" if goals[team] < goals[opp] else "D"
            row[{"W": "won", "D": "drawn", "L": "lost"}[result]] += 1
            row["points"] += {"W": 3, "D": 1, "L": 0}[result]
            row["form"] = ([*row["form"], result])[-5:]
            starters = squads[team][:11]
            for p in starters:
                s = stats[p.player_id]
                s["appearances"] += 1
                s["minutes"] += 90
                s["passes"] += rng.randint(18, 70) if p.position != "GK" else rng.randint(15, 30)
                s["pass_acc"].append(rng.uniform(0.72, 0.92))
                s["difficulty"].append(rng.uniform(0.25, 0.5))
                s["top_speed_kmh"] = max(
                    s["top_speed_kmh"], round(p.top_speed_kmh - rng.uniform(0, 1.6), 1)
                )
                s["distance_km"] += round(rng.uniform(9.0, 11.8) if p.position != "GK" else 5.2, 1)
                s["shots"] += _poisson(rng, {"FW": 2.2, "MF": 1.0, "DF": 0.3, "GK": 0}[p.position])
                if rng.random() < (100 - p.attributes.discipline) / 400:
                    # A ban is served at the threshold and the count starts again.
                    s["yellow_cards"] = (s["yellow_cards"] + 1) % 5
            weights = [goal_weight[p.position] for p in starters]
            for _ in range(goals[team]):
                scorer = rng.choices(starters, weights)[0]
                stats[scorer.player_id]["goals"] += 1
                stats[scorer.player_id]["shots"] += 1
                stats[scorer.player_id]["last_goal_matchday"] = md
                others = [p for p in starters if p is not scorer and p.position != "GK"]
                if rng.random() < 0.75:
                    stats[rng.choice(others).player_id]["assists"] += 1

    # The card story needs Halloway on four yellows, one short of a ban.
    stats["ash-03"]["yellow_cards"] = 4
    ordered = sorted(
        rows.values(),
        key=lambda r: (-r["points"], -(r["goals_for"] - r["goals_against"]), -r["goals_for"]),
    )
    table = [
        {**r, "position": i, "goal_difference": r["goals_for"] - r["goals_against"]}
        for i, r in enumerate(ordered, start=1)
    ]
    players = []
    for s in stats.values():
        acc, diff = s.pop("pass_acc"), s.pop("difficulty")
        s["pass_accuracy"] = round(sum(acc) / len(acc), 3) if acc else None
        s["avg_pass_difficulty"] = round(sum(diff) / len(diff), 3) if diff else None
        s["top_speed_kmh"] = s["top_speed_kmh"] or None
        s["distance_km"] = round(s["distance_km"], 1)
        s["suspended_for"] = []
        players.append(s)
    return Season.model_validate(
        {"schema_version": SCHEMA_VERSION, "league_id": LEAGUE_ID, "season_id": SEASON_ID,
         "through_matchday": MATCHDAY - 1, "table": table, "fixtures": fixtures,
         "players": players}
    )  # fmt: skip


# ---------------------------------------------------------------------------------------
# The storyboard. Positions are written in the pitch frame (Ashmere attack +x) and
# converted to each team's attacking frame when the events are emitted.
# ---------------------------------------------------------------------------------------


@dataclass
class Beat:
    t: float
    type: str
    team: str | None = None
    player: str | None = None
    start: tuple[float, float] | None = None
    end: tuple[float, float] | None = None
    travel: float = 0.0  # seconds the ball takes from start to end
    outcome: str | None = None
    receiver: str | None = None
    related: str | None = None
    lofted: float = 0.0  # peak ball height for lofted deliveries
    q: dict[str, Any] = field(default_factory=dict)


B = Beat
STORY: list[Beat] = [
    B(0.0, "period_start"),
    B(0.0, "kick_off", "ash", "ash-09", (52.5, 34), (46, 30), 0.7, "complete", "ash-08"),
    B(1.6, "pass", "ash", "ash-08", (46, 30), (24, 26), 1.5, "complete", "ash-04"),
    B(4.4, "pass", "ash", "ash-04", (24, 26), (31, 9), 1.1, "complete", "ash-02"),
    B(6.0, "carry", "ash", "ash-02", (31, 9), (39, 8), 2.2),
    B(8.6, "pass", "ash", "ash-02", (39, 8), (54, 6), 1.1, "complete", "ash-07"),
    B(10.0, "pressure", "brk", "brk-03", (51, 62), None, 0, "won", related="ash-07"),
    B(10.6, "tackle", "brk", "brk-03", (50.5, 62), None, 0, "won", related="ash-07"),
    B(11.4, "pass", "brk", "brk-03", (54.5, 6.5), (60, 25), 1.2, "complete", "brk-06"),
    B(13.4, "pass", "brk", "brk-06", (60, 25), (46, 31), 1.3, "complete", "brk-10"),
    B(14.8, "carry", "brk", "brk-10", (46, 31), (37, 37), 2.2),
    B(17.2, "pass", "brk", "brk-10", (37, 37), (28, 14), 1.4, "complete", "brk-11"),
    B(18.7, "carry", "brk", "brk-11", (28, 14), (19, 11), 1.5),
    B(20.3, "pass", "brk", "brk-11", (19, 11), (9, 35), 1.3, "complete", "brk-09", lofted=4.0,
      q={"pass_type": "cross"}),
    B(21.6, "shot", "brk", "brk-09", (9, 35), (0, 38), 0.4, "blocked",
      q={"body_part": "head", "xg": 0.18, "shot_speed_kmh": 54}),
    # Blocked behind by Ashmere's centre back: corner to Brackenford, 14 s to set up.
    B(36.0, "corner", "brk", "brk-07", (0.4, 67.6), (8, 31), 1.5, "complete", "brk-05",
      lofted=6.0),
    B(37.5, "shot", "brk", "brk-05", (8, 31), (-0.5, 31.5), 0.5, "off_target",
      q={"body_part": "head", "xg": 0.09, "shot_speed_kmh": 48, "end_height_m": 3.1}),
    # Goal kick, then the twelve-second move that ends in the goal.
    B(48.0, "goal_kick", "ash", "ash-01", (6, 30), (20, 21), 1.5, "complete", "ash-05"),
    B(50.4, "pass", "ash", "ash-05", (20, 21), (31, 29), 1.2, "complete", "ash-06"),
    B(51.6, "carry", "ash", "ash-06", (31, 29), (37, 31), 1.8),
    B(53.4, "pass", "ash", "ash-06", (37, 31), (49, 39), 1.3, "complete", "ash-08"),
    B(54.6, "pressure", "brk", "brk-06", (57, 30), None, 0, "lost", related="ash-08"),
    B(54.7, "carry", "ash", "ash-08", (49, 39), (56, 37), 1.3),
    B(56.0, "pass", "ash", "ash-08", (56, 37), (80, 29), 1.6, "complete", "ash-09",
      q={"pass_type": "through", "line_breaking": True, "difficulty": 0.71,
         "pressure_on_passer": 0.4, "ball_speed_kmh": 58}),
    B(57.6, "carry", "ash", "ash-09", (80, 29), (92, 32), 1.4),
    B(59.0, "shot", "ash", "ash-09", (92, 32), (105, 36.4), 0.45, "goal",
      q={"body_part": "right_foot", "xg": 0.27, "shot_speed_kmh": 104, "end_height_m": 0.9,
         "pressure_on_passer": 0.3}),
    B(59.0, "goal", "ash", "ash-09", (92, 32), (105, 36.4), 0, None,
      q={"assist_player_id": "ash-08", "score_home": 1, "score_away": 0}),
    # Celebrations, then Brackenford kick off.
    B(112.0, "kick_off", "brk", "brk-09", (52.5, 34), (58, 38), 0.7, "complete", "brk-10"),
    B(113.4, "pass", "brk", "brk-10", (58, 38), (66, 30), 1.0, "complete", "brk-06"),
    B(115.6, "pass", "brk", "brk-06", (66, 30), (60, 58), 1.6, "complete", "brk-08"),
    B(117.4, "carry", "brk", "brk-08", (60, 58), (45, 59), 3.4),
    B(120.9, "foul", "ash", "ash-03", (44.6, 59.2), None, 0, related="brk-08",
      q={"severity": 0.78, "reason": "late_tackle"}),
    B(131.0, "card", "ash", "ash-03", (44.6, 59.2), None, 0, "yellow",
      q={"reason": "reckless_tackle"}),
    B(144.0, "free_kick", "brk", "brk-08", (44.6, 59.2), (31, 40), 1.4, "complete", "brk-10"),
    B(146.2, "pass", "brk", "brk-10", (31, 40), (26, 35), 0.7, "incomplete", "brk-09"),
    B(146.9, "interception", "ash", "ash-06", (26, 35), None, 0),
    B(147.6, "carry", "ash", "ash-06", (26, 35), (33, 38), 1.8),
    B(149.6, "pass", "ash", "ash-06", (33, 38), (45, 49), 1.3, "complete", "ash-10"),
    B(151.8, "pass", "ash", "ash-10", (45, 49), (26, 42), 1.6, "complete", "ash-05"),
    B(154.4, "pass", "ash", "ash-05", (26, 42), (7, 33), 1.6, "complete", "ash-01"),
    B(158.5, "pass", "ash", "ash-01", (7, 33), (22, 23), 1.4, "complete", "ash-04"),
    B(160.2, "carry", "ash", "ash-04", (22, 23), (30, 24), 2.4),
    B(163.0, "pass", "ash", "ash-04", (30, 24), (38, 31), 1.0, "complete", "ash-06"),
    B(164.8, "pass", "ash", "ash-06", (38, 31), (48, 22), 1.1, "complete", "ash-08"),
    B(166.2, "carry", "ash", "ash-08", (48, 22), (55, 20), 2.0),
    B(168.6, "pass", "ash", "ash-08", (55, 20), (64, 8), 1.2, "complete", "ash-07"),
    B(170.2, "carry", "ash", "ash-07", (64, 8), (71, 7), 2.4),
    B(173.0, "pressure", "brk", "brk-03", (34, 61), None, 0, "won", related="ash-07"),
    B(173.6, "pass", "ash", "ash-07", (71, 7), (78, 28.5), 1.0, "incomplete", "ash-09"),
    B(174.6, "interception", "brk", "brk-04", (27, 39.5), None, 0),
    B(175.2, "pass", "brk", "brk-04", (78, 28.5), (52, 30), 1.8, "incomplete", "brk-09"),
]  # fmt: skip
"""The match as it happened, in time order. See ``_pitch_point`` for the one exception to
the pitch-frame rule."""

DEFENSIVE = {"pressure", "tackle", "interception"}


def _pitch_point(beat: Beat, point: tuple[float, float]) -> tuple[float, float]:
    """Storyboard points are in the pitch frame, except defensive actions by Brackenford,
    which are written where the defender stands in Brackenford's attacking frame."""
    if beat.type in DEFENSIVE and beat.team == AWAY:
        return (PITCH_LENGTH_M - point[0], PITCH_WIDTH_M - point[1])
    return point


def direction_of(team: str, period: int = 1) -> Direction:
    return attacking_direction(HOME_DIRECTION, team == HOME, period)


def build_events() -> list[dict[str, Any]]:
    events = []
    possession = 0
    in_possession: str | None = None
    for i, beat in enumerate(STORY, start=1):
        if _wins_ball(beat) and beat.team != in_possession:
            possession += 1
            in_possession = beat.team
        event: dict[str, Any] = {
            "event_id": f"{MATCH_ID}-e{i:04d}",
            "match_id": MATCH_ID,
            "t": beat.t,
            "period": 1,
            "clock": format_clock(beat.t, 1, 0.0),
            "type": beat.type,
            "team_id": beat.team,
            "player_id": beat.player,
            "outcome": beat.outcome,
            "receiver_id": beat.receiver,
            "related_player_id": beat.related,
            "possession_id": f"{MATCH_ID}-p{possession:03d}" if beat.team else None,
        }
        q = dict(beat.q)
        if beat.team:
            d = direction_of(beat.team)
            if beat.start:
                start = _pitch_point(beat, beat.start)
                event["start"] = list(_r2(to_attacking(start, d)))
            if beat.end:
                event["end"] = list(_r2(to_attacking(beat.end, d)))
                if beat.type in {"pass", "carry", "corner", "free_kick", "goal_kick", "kick_off"}:
                    q.setdefault("distance_m", round(math.dist(beat.start or (0, 0), beat.end), 1))
            if beat.type == "carry":
                q["duration_s"] = beat.travel
            if beat.lofted:
                q.setdefault("pass_type", "lofted")
        event["qualifiers"] = q
        events.append(MatchEvent.model_validate(event).model_dump(mode="json", exclude_none=True))
    return events


def _r2(p: tuple[float, float]) -> tuple[float, float]:
    return (round(p[0], 2), round(p[1], 2))


# ---------------------------------------------------------------------------------------
# Tracking frames. The ball follows the storyboard; players follow their team's shape,
# which shifts with the ball, and break from it to reach the ball when they act on it.
# ---------------------------------------------------------------------------------------

GOAL_T = 59.0
CELEBRATION = {  # Ashmere players run to the corner flag after the goal
    "ash-09": (99.0, 63.0), "ash-08": (97.0, 61.0), "ash-11": (96.0, 63.5),
    "ash-07": (95.0, 60.0), "ash-10": (93.0, 58.0),
}  # fmt: skip


def ball_keyframes() -> list[tuple[float, float, float, float]]:
    """(t, x, y, z) in the pitch frame, plus the peak of each lofted delivery."""
    keys: list[tuple[float, float, float, float]] = []
    for beat in STORY:
        if beat.start is None or beat.type in DEFENSIVE | {"foul", "card", "goal"}:
            continue
        start = _pitch_point(beat, beat.start)
        keys.append((beat.t, *start, BALL_RADIUS))
        if beat.end:
            t_end = beat.t + beat.travel
            if beat.lofted:
                mid = ((start[0] + beat.end[0]) / 2, (start[1] + beat.end[1]) / 2)
                keys.append((beat.t + beat.travel / 2, *mid, beat.lofted))
            z_end = beat.q.get("end_height_m", BALL_RADIUS)
            keys.append((t_end, *beat.end, z_end))
    # The goal: the ball nestles in the net, then is carried back for the restart.
    keys += [(GOAL_T + 0.7, 106.6, 36.0, 0.4), (GOAL_T + 1.5, 106.8, 35.6, BALL_RADIUS),
             (98.0, 106.8, 35.6, BALL_RADIUS), (106.0, 52.5, 34.0, BALL_RADIUS)]  # fmt: skip
    # The off-target header leaves play; the goal kick restarts at the six-yard box.
    keys += [(39.0, -4.0, 31.6, 1.5), (44.0, -4.0, 31.6, BALL_RADIUS)]
    # The foul: the ball runs loose, then is placed for the free kick.
    keys += [(122.0, 43.0, 61.0, BALL_RADIUS), (139.0, 44.6, 59.2, BALL_RADIUS)]
    # The blocked header: deflects behind for the corner, then is placed at the flag.
    keys += [(22.4, -2.0, 45.0, 0.6), (30.0, 0.4, 67.6, BALL_RADIUS)]
    keys.sort()
    return keys


def _interp(keys: Sequence[tuple[float, ...]], t: float) -> tuple[float, ...]:
    if t <= keys[0][0]:
        return keys[0][1:]
    for (t0, *a), (t1, *b) in pairwise(keys):
        if t0 <= t <= t1:
            if t1 == t0:
                return tuple(b)
            f = (t - t0) / (t1 - t0)
            return tuple(x + (y - x) * f for x, y in zip(a, b, strict=True))
    return keys[-1][1:]


def _ball_z(keys: list[tuple[float, float, float, float]], t: float) -> float:
    """Height along a smooth arc between keyframes rather than straight lines."""
    for (t0, _, _, z0), (t1, _, _, z1) in pairwise(keys):
        if t0 <= t <= t1 and t1 > t0:
            f = (t - t0) / (t1 - t0)
            return z0 + (z1 - z0) * (1 - math.cos(math.pi * f)) / 2
    return BALL_RADIUS


def player_waypoints() -> dict[str, list[tuple[float, float, float]]]:
    """Where and when each player must be to make the storyboard true."""
    points: dict[str, list[tuple[float, float, float]]] = {}

    def add(pid: str | None, t: float, p: tuple[float, float]) -> None:
        if pid:
            points.setdefault(pid, []).append((t, p[0], p[1]))

    for beat in STORY:
        if beat.start is None or beat.type == "goal":
            continue
        start = _pitch_point(beat, beat.start)
        if beat.type == "card":
            continue
        add(beat.player, beat.t, start)
        if beat.type == "carry" and beat.end:
            add(beat.player, beat.t + beat.travel, beat.end)
        if beat.receiver and beat.end and beat.outcome == "complete":
            add(beat.receiver, beat.t + beat.travel, beat.end)
    # The striker's run onto the through ball starts deep.
    add("ash-09", 54.4, (60.0, 38.0))
    # Brackenford's centre back walks up for the corner.
    for t, spot in ((24.0, (60.0, 30.0)), (28.0, (32.0, 34.0)), (32.0, (14.0, 36.0))):
        add("brk-05", t, spot)
    add("brk-05", 35.0, (11.0, 34.0))
    for pid, spot in CELEBRATION.items():
        for hold in range(9, 27, 2):
            add(pid, GOAL_T + hold, spot)
    for pts in points.values():
        pts.sort()
    return points


def shape_position(
    slot: str, team: str, ball_x: float, ball_y: float, in_possession: bool
) -> tuple[float, float]:
    """Where a player stands in the team's shape, given a (smoothed) ball position."""
    x, y = SLOT_XY[slot]
    d = direction_of(team)
    bx = ball_x if d == "+x" else PITCH_LENGTH_M - ball_x
    by = ball_y if d == "+x" else PITCH_WIDTH_M - ball_y
    shift = (bx - 52.5) * 0.55 + (6.0 if in_possession else -4.0)
    if slot != "GK":
        x = min(max(x + shift, 8.0), 98.0)
        y = y + (by - 34.0) * 0.25
    else:
        x = min(max(x + shift * 0.15, 2.0), 16.0)
        y = 34.0 + (by - 34.0) * 0.15
    return (x, y) if d == "+x" else (PITCH_LENGTH_M - x, PITCH_WIDTH_M - y)


def _wins_ball(beat: Beat) -> bool:
    """Whether this beat leaves ``beat.team`` in possession."""
    if beat.team is None or beat.type in {"pressure", "foul", "card", "goal"}:
        return False
    return not (beat.type == "tackle" and beat.outcome == "lost")


def possession_at(t: float) -> str:
    team = HOME
    for beat in STORY:
        if beat.t > t:
            break
        if _wins_ball(beat):
            team = beat.team or team
    return team


def build_frames(meta: MatchMeta, league: League) -> list[dict[str, Any]]:
    keys = ball_keyframes()
    waypoints = player_waypoints()
    top_speed = {p.player_id: p.top_speed_kmh / 3.6 for c in league.clubs for p in c.squad}
    lineup = [(meta.home.team_id, e) for e in meta.home.starting] + [
        (meta.away.team_id, e) for e in meta.away.starting
    ]
    n = int(END_T * FRAME_RATE_HZ) + 1
    dt = 1 / FRAME_RATE_HZ
    smooth_bx, smooth_by = 52.5, 34.0
    pos: dict[str, tuple[float, float]] = {}
    frames = []
    for i in range(n):
        t = round(i * dt, 1)
        bx, by = _interp(keys, t)[:2]
        bz = _ball_z(keys, t)
        alpha = dt / 2.0  # the shape lags the ball by about two seconds
        smooth_bx += (bx - smooth_bx) * alpha
        smooth_by += (by - smooth_by) * alpha
        team_in_possession = possession_at(t)
        players: dict[str, list[float]] = {}
        for team, entry in lineup:
            pid = entry.player_id
            target = shape_position(
                entry.slot, team, smooth_bx, smooth_by, team == team_in_possession
            )
            if 100.0 < t < 112.0:  # back into kick-off shape before the restart
                target = shape_position(entry.slot, team, 52.5, 34.0, team == AWAY)
                target = _own_half(team, target)
            if t < 0.5:
                target = _own_half(team, shape_position(entry.slot, team, 52.5, 34.0, True))
            prev = pos.get(pid, target)
            vmax = top_speed[pid] * 0.7  # jogging to hold the shape
            wp = _active_waypoint(waypoints.get(pid, []), t)
            if wp is not None:
                due, target = wp
                # Run only as fast as needed to arrive on time, never above top speed.
                needed = math.dist(prev, target) / max(due - t, dt)
                vmax = min(top_speed[pid], max(needed, 2.0))
            step = math.dist(prev, target)
            if step > vmax * dt and i > 0:
                f = vmax * dt / step
                new = (prev[0] + (target[0] - prev[0]) * f, prev[1] + (target[1] - prev[1]) * f)
            else:
                new = target
            vx, vy = ((new[0] - prev[0]) / dt, (new[1] - prev[1]) / dt) if i else (0.0, 0.0)
            pos[pid] = new
            players[pid] = [round(new[0], 2), round(new[1], 2), round(vx, 2), round(vy, 2)]
        frame = {"t": t, "ball": [round(bx, 2), round(by, 2), round(bz, 2)], "players": players}
        frames.append(Frame.model_validate(frame).model_dump(mode="json"))
    return frames


def _own_half(team: str, p: tuple[float, float]) -> tuple[float, float]:
    if direction_of(team) == "+x":
        return (min(p[0], 51.5), p[1])
    return (max(p[0], 53.5), p[1])


def _active_waypoint(
    points: list[tuple[float, float, float]], t: float
) -> tuple[float, tuple[float, float]] | None:
    """The next waypoint if it is close in time, or the last one held briefly.

    Returns the time the player is due there and the point.
    """
    for wt, x, y in points:
        if t <= wt and wt - t <= 3.5:
            return wt, (x, y)
    for wt, x, y in reversed(points):
        if wt <= t <= wt + 0.6:
            return t, (x, y)
    return None


def top_speed_in(frames: list[dict[str, Any]], pid: str, t0: float, t1: float) -> float:
    speeds = [
        math.hypot(f["players"][pid][2], f["players"][pid][3]) * 3.6
        for f in frames
        if t0 <= f["t"] <= t1 and pid in f["players"]
    ]
    # Report the peak of a 0.5 s rolling mean, as tracking providers do, not one noisy step.
    window = FRAME_RATE_HZ // 2
    rolling = [sum(speeds[i : i + window]) / window for i in range(len(speeds) - window + 1)]
    return round(max(rolling), 1)


def distance_in(frames: list[dict[str, Any]], pid: str, t0: float, t1: float) -> float:
    pts = [f["players"][pid][:2] for f in frames if t0 <= f["t"] <= t1]
    return round(sum(math.dist(a, b) for a, b in pairwise(pts)), 1)


# ---------------------------------------------------------------------------------------
# Match metadata, moments and cues. Moments and cues are what the detector and agents
# would produce; they are written here by hand as worked examples of each contract.
# ---------------------------------------------------------------------------------------


def build_meta(league: League) -> MatchMeta:
    clubs = {c.team_id: c for c in league.clubs}

    def sheet(team: str) -> dict[str, Any]:
        club = clubs[team]
        slots = FORMATIONS[club.formation]
        return {
            "team_id": team,
            "formation": club.formation,
            "starting": [{"player_id": f"{team}-{s:02d}", "slot": slot} for s, _, _, slot in slots],
            "bench": [f"{team}-{s:02d}" for s, _, _ in BENCH],
        }

    return MatchMeta.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "match_id": MATCH_ID,
            "league_id": LEAGUE_ID,
            "season_id": SEASON_ID,
            "matchday": MATCHDAY,
            "seed": None,
            "kickoff_local": "2026-10-24T15:00:00",
            "stadium": clubs[HOME].stadium,
            "referee": "Marta Velling",
            "weather": {"condition": "overcast", "temperature_c": 11.0, "wind_kmh": 14.0},
            "home": sheet(HOME),
            "away": sheet(AWAY),
            "home_attacks_in_period_1": HOME_DIRECTION,
            "stakes": {"derby": True, "notes": ["Kilnside derby"]},
            "pre_match_win_prob": {"home": 0.44, "draw": 0.28, "away": 0.28},
        }
    )


def event_id(beat_index: int) -> str:
    return f"{MATCH_ID}-e{beat_index:04d}"


def find(type_: str, player: str, t: float | None = None) -> int:
    for i, b in enumerate(STORY, start=1):
        if b.type == type_ and b.player == player and (t is None or b.t == t):
            return i
    raise KeyError((type_, player, t))


def build_moments(
    frames: list[dict[str, Any]], season: Season, league: League
) -> list[dict[str, Any]]:
    names = {p.player_id: p.short_name for c in league.clubs for p in c.squad}
    pstats = {p.player_id: p for p in season.players}
    table = {r.team_id: r for r in season.table}
    window = (48.0, 59.6)
    through = find("pass", "ash-08", 56.0)
    shot = find("shot", "ash-09", 59.0)
    striker_speed = top_speed_in(frames, "ash-09", *window)
    striker_dist = distance_in(frames, "ash-09", *window)
    goals_before = pstats["ash-09"].goals
    last_goal = pstats["ash-09"].last_goal_matchday
    drought = MATCHDAY - last_goal if last_goal else None
    through_q = STORY[through - 1].q
    shot_q = STORY[shot - 1].q
    through_beat = STORY[through - 1]
    pass_len = round(math.dist(through_beat.start or (0, 0), through_beat.end or (0, 0)), 1)

    evidence = [
        {"id": "ev1", "claim_type": "stat", "source": event_id(through),
         "value": f"{pass_len} m line-breaking through ball, difficulty {through_q['difficulty']}",
         "numbers": {"distance_m": pass_len, "difficulty": through_q["difficulty"]}},
        {"id": "ev2", "claim_type": "stat", "source": f"track:ash-09:{window[0]}-{window[1]}",
         "value": f"{names['ash-09']} reached {striker_speed} km/h, covering {striker_dist} m",
         "numbers": {"top_speed_kmh": striker_speed, "distance_m": striker_dist}},
        {"id": "ev3", "claim_type": "stat", "source": event_id(shot),
         "value": f"Shot at {shot_q['shot_speed_kmh']} km/h, xG {shot_q['xg']}",
         "numbers": {"shot_speed_kmh": shot_q["shot_speed_kmh"], "xg": shot_q["xg"]}},
        {"id": "ev4", "claim_type": "season", "source": "season:ash-09:goals",
         "value": f"{names['ash-09']} now has {goals_before + 1} league goals this season",
         "numbers": {"goals": goals_before + 1}},
        {"id": "ev5", "claim_type": "win_prob", "source": "winprob:m017:59.0",
         "value": "Ashmere win probability 44% to 63%",
         "numbers": {"before": 0.44, "after": 0.63}},
        {"id": "ev6", "claim_type": "table", "source": "table:ash",
         "value": f"Ashmere started the day {_ordinal(table['ash'].position)} on "
                  f"{table['ash'].points} points",
         "numbers": {"position": table["ash"].position, "points": table["ash"].points}},
    ]  # fmt: skip
    if drought is not None and drought >= 3:
        evidence.append(
            {"id": "ev7", "claim_type": "milestone", "source": "season:ash-09:last_goal",
             "value": f"First goal in {drought} league matches",
             "numbers": {"matches": drought}}
        )  # fmt: skip

    def ev_ids(*ids: str) -> list[str]:
        known = {e["id"] for e in evidence}
        return [i for i in ids if i in known]

    shot_speed = shot_q["shot_speed_kmh"]
    scorer_headline = f"{names['ash-09']}: {striker_speed} km/h, then {shot_speed} km/h"
    scorer_body = (
        f"{names['ash-09']} hit {striker_speed} km/h onto the through ball and finished at "
        f"{shot_q['shot_speed_kmh']} km/h. That's {goals_before + 1} league goals this season."
    )
    goal = {
        "moment_id": f"{MATCH_ID}-mo03",
        "match_id": MATCH_ID,
        "type": "goal",
        "period": 1,
        "t_start": window[0],
        "t_peak": 59.0,
        "t_end": window[1],
        "replay_window": list(window),
        "importance": 0.92,
        "scoring_team": HOME,
        "involved": [
            {"player_id": "ash-09", "role": "scorer", "touches": 2,
             "events": [event_id(find("carry", "ash-09")), event_id(shot)],
             "top_speed_kmh": striker_speed, "distance_in_window_m": striker_dist},
            {"player_id": "ash-08", "role": "assist", "touches": 2,
             "events": [event_id(find("carry", "ash-08", 54.7)), event_id(through)],
             "top_speed_kmh": top_speed_in(frames, "ash-08", *window),
             "distance_in_window_m": distance_in(frames, "ash-08", *window)},
            {"player_id": "ash-06", "role": "build_up", "touches": 2,
             "events": [event_id(find("carry", "ash-06", 51.6)),
                        event_id(find("pass", "ash-06", 53.4))],
             "top_speed_kmh": top_speed_in(frames, "ash-06", *window),
             "distance_in_window_m": distance_in(frames, "ash-06", *window)},
        ],
        "win_prob_before": {"home": 0.44, "draw": 0.28, "away": 0.28},
        "win_prob_after": {"home": 0.63, "draw": 0.23, "away": 0.14},
        "swing": 0.19,
        "context_refs": ["season:ash-09:goals", "season:ash-09:last_goal", "table:ash",
                         "fixture:ash:next"],
        "evidence": evidence,
        "drafts": {
            "player": {
                "ash-09": {"lens": "player", "subject_id": "ash-09", "headline": scorer_headline,
                           "body": scorer_body, "evidence_ids": ev_ids("ev2", "ev3", "ev4"),
                           "agent": "player-agent:ash-09"},
                "ash-08": {"lens": "player", "subject_id": "ash-08",
                           "headline": f"{names['ash-08']} splits the line",
                           "body": f"A {pass_len} m through ball under pressure, rated "
                                   f"{through_q['difficulty']} difficulty, put the striker clean "
                                   "through.",
                           "evidence_ids": ev_ids("ev1"), "agent": "player-agent:ash-08"},
                "ash-06": {"lens": "player", "subject_id": "ash-06",
                           "headline": f"{names['ash-06']} starts it",
                           "body": "Took the ball off the centre back, carried it into midfield "
                                   "and found the pass that started the move.",
                           "evidence_ids": [], "author": "template"},
            },
            "club": {
                "ash": {"lens": "club", "subject_id": "ash",
                        "headline": "Derby lead for Ashmere",
                        "body": "One up in the Kilnside derby, and the win chance jumps from "
                                "44% to 63%.",
                        "evidence_ids": ev_ids("ev5"), "agent": "club-agent:ash"},
                "brk": {"lens": "club", "subject_id": "brk", "kind": "no_box",
                        "agent": "club-agent:brk"},
            },
            "pundit": {"lens": "pundit", "headline": "One pass, two lines gone",
                       "body": f"{names['ash-08']} turned away from the press and played through "
                               "both Brackenford lines. The striker's run was already on.",
                       "evidence_ids": ev_ids("ev1", "ev2"), "agent": "pundit-agent"},
        },
        "verdicts": {
            "player:ash-09": {"status": "approved"},
            "player:ash-08": {"status": "approved"},
            "player:ash-06": {"status": "fallback",
                              "issues": ["Player agent timed out; template box used"]},
            "club:ash": {"status": "approved"},
            "pundit": {"status": "repaired",
                       "issues": ["Draft said 'three lines'; evidence ev1 supports one "
                                  "line-breaking pass. Rewritten."]},
        },
        "director": {"show": ["player:ash-09", "player:ash-08", "player:ash-06", "club:ash",
                              "pundit"],
                     "camera": "spidercam_goal", "replay_at_t": 61.0,
                     "budget_left": {"player:ash-09": 7, "player:ash-08": 7, "player:ash-06": 7,
                                     "club:ash": 7, "pundit": 7}},
        "status": "scheduled",
    }  # fmt: skip

    corner_shot = find("shot", "brk-09")
    corner = {
        "moment_id": f"{MATCH_ID}-mo01",
        "match_id": MATCH_ID,
        "type": "corner",
        "period": 1,
        "t_start": 17.2,
        "t_peak": 37.5,
        "t_end": 38.2,
        "replay_window": [17.2, 22.4],
        "importance": 0.34,
        "involved": [
            {"player_id": "brk-09", "role": "shooter", "touches": 1,
             "events": [event_id(corner_shot)]},
            {"player_id": "brk-07", "role": "taker", "touches": 1,
             "events": [event_id(find("corner", "brk-07"))]},
        ],
        "win_prob_before": {"home": 0.44, "draw": 0.28, "away": 0.28},
        "win_prob_after": {"home": 0.44, "draw": 0.28, "away": 0.28},
        "swing": 0.0,
        "evidence": [
            {"id": "ev1", "claim_type": "stat", "source": event_id(corner_shot),
             "value": "Header blocked behind, xG 0.18", "numbers": {"xg": 0.18}},
        ],
        "director": {"camera": "corner_low"},
        "status": "detected",
    }  # fmt: skip

    halloway = pstats["ash-03"]
    threshold = season.rules.yellow_card_ban_threshold
    next_fixture = next(
        f for f in season.fixtures
        if f.matchday == MATCHDAY + 1 and HOME in (f.home_id, f.away_id)
    )  # fmt: skip
    opponent = next_fixture.away_id if next_fixture.home_id == HOME else next_fixture.home_id
    opponent_name = {c.team_id: c.short_name for c in league.clubs}[opponent]
    card = {
        "moment_id": f"{MATCH_ID}-mo04",
        "match_id": MATCH_ID,
        "type": "card",
        "period": 1,
        "t_start": 117.4,
        "t_peak": 131.0,
        "t_end": 132.0,
        "replay_window": [117.4, 122.0],
        "importance": 0.55,
        "involved": [
            {"player_id": "ash-03", "role": "fouler", "touches": 1,
             "events": [event_id(find("foul", "ash-03")), event_id(find("card", "ash-03"))]},
            {"player_id": "brk-08", "role": "fouled", "touches": 1,
             "events": [event_id(find("carry", "brk-08"))]},
        ],
        "win_prob_before": {"home": 0.63, "draw": 0.23, "away": 0.14},
        "win_prob_after": {"home": 0.62, "draw": 0.23, "away": 0.15},
        "swing": -0.01,
        "context_refs": ["season:ash-03:yellow_cards", f"fixture:ash:next:{next_fixture.match_id}"],
        "evidence": [
            {"id": "ev1", "claim_type": "discipline", "source": "season:ash-03:yellow_cards",
             "value": f"{names['ash-03']}'s yellow card number {halloway.yellow_cards + 1}; "
                      f"{threshold} brings a one-match ban",
             "numbers": {"yellows": halloway.yellow_cards + 1, "threshold": threshold}},
            {"id": "ev2", "claim_type": "fixture", "source": f"fixture:{next_fixture.match_id}",
             "value": f"Next match: away at {opponent_name}, matchday {next_fixture.matchday}",
             "numbers": {"matchday": next_fixture.matchday}},
        ],
        "drafts": {
            "club": {
                "ash": {"lens": "club", "subject_id": "ash",
                        "headline": f"{names['ash-03']} banned for {opponent_name}",
                        "body": f"That's his {_ordinal(halloway.yellow_cards + 1)} yellow, so "
                                f"he misses next week's trip to {opponent_name}.",
                        "evidence_ids": ["ev1", "ev2"], "agent": "club-agent:ash"},
            },
        },
        "verdicts": {"club:ash": {"status": "approved"}},
        "director": {"show": ["club:ash"], "camera": "card_close", "replay_at_t": 133.0,
                     "budget_left": {"club:ash": 6}},
        "status": "scheduled",
    }  # fmt: skip
    return [Moment.model_validate(m).model_dump(mode="json") for m in (corner, goal, card)]


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def build_cues(moments: list[dict[str, Any]]) -> dict[str, Any]:
    goal = next(m for m in moments if m["type"] == "goal")
    card = next(m for m in moments if m["type"] == "card")
    evidence = {e["id"]: e for e in goal["evidence"]}
    window = goal["replay_window"]
    speed = goal["involved"][0]["top_speed_kmh"]

    def box(draft: dict[str, Any], ev: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {"headline": draft["headline"], "body": draft["body"],
                "evidence": [ev[i] for i in draft["evidence_ids"]], **extra}  # fmt: skip

    d = goal["drafts"]
    analyst = {
        "event_ids": [e for inv in goal["involved"] for e in inv["events"]],
        "pass_map": [[37, 31, 49, 39], [56, 37, 80, 29]],
        "notes": ["Pressure on the passer 0.4 when the through ball was played"],
    }
    camera = {"shot": "spidercam_goal", "replay": window, "trail": True}
    cues: list[dict[str, Any]] = [
        {"t_show": 57.9, "duration": 3, "layer": "player", "template": "speed_badge",
         "player_id": "ash-09", "badge": {"player_id": "ash-09", "speed_kmh": speed}},
        {"t_show": 61.0, "duration": 12, "layer": "global", "template": "replay",
         "priority": 0.92, "camera": {**camera, "highlight": None, "trail": False}},
    ]  # fmt: skip
    for pid in ("ash-09", "ash-08", "ash-06"):
        inv = next(i for i in goal["involved"] if i["player_id"] == pid)
        cues.append(
            {"t_show": 61.0, "duration": 12, "layer": "player", "template": "replay",
             "player_id": pid, "priority": 0.92,
             "camera": {**camera, "highlight": pid, "speedo": inv["top_speed_kmh"]}}
        )  # fmt: skip
        cues.append(
            {"t_show": 73.0, "duration": 8, "layer": "player", "template": "fact_box",
             "player_id": pid, "priority": 0.92,
             "box": box(d["player"][pid], evidence, analyst=analyst)}
        )  # fmt: skip
    cues.append(
        {"t_show": 73.0, "duration": 8, "layer": "player", "template": "fact_box", "lang": "es",
         "player_id": "ash-09", "priority": 0.92,
         "box": {"headline": f"Varrow: {speed} km/h, y luego 104 km/h",
                 "body": f"Varrow alcanzó {speed} km/h hacia el pase al hueco y definió a "
                         f"104 km/h. Ya suma {int(evidence['ev4']['numbers']['goals'])} goles "
                         "de liga esta temporada.",
                 "evidence": [evidence[i] for i in d["player"]["ash-09"]["evidence_ids"]]}}
    )  # fmt: skip
    cues.append(
        {"t_show": 73.0, "duration": 8, "layer": "club", "template": "fact_box", "team_id": "ash",
         "priority": 0.9, "camera": camera, "box": box(d["club"]["ash"], evidence)}
    )  # fmt: skip
    cues.append(
        {"t_show": 73.0, "duration": 8, "layer": "pundit", "template": "fact_box",
         "priority": 0.85, "box": box(d["pundit"], evidence, analyst=analyst)}
    )  # fmt: skip
    card_ev = {e["id"]: e for e in card["evidence"]}
    cues.append(
        {"t_show": 133.0, "duration": 6, "layer": "club", "template": "replay", "team_id": "ash",
         "camera": {"shot": "card_close", "replay": card["replay_window"],
                    "highlight": "ash-03"}}
    )  # fmt: skip
    cues.append(
        {"t_show": 139.0, "duration": 8, "layer": "club", "template": "fact_box",
         "team_id": "ash", "priority": 0.7, "box": box(card["drafts"]["club"]["ash"], card_ev)}
    )  # fmt: skip
    corner = next(m for m in moments if m["type"] == "corner")
    cues.append(
        {"t_show": 30.0, "duration": 6, "layer": "pundit", "template": "timeline_item",
         "priority": 0.2, "moment_id": corner["moment_id"],
         "box": {"headline": "Corner, Brackenford", "body": "Header blocked behind.",
                 "evidence": corner["evidence"]}}
    )  # fmt: skip

    cues.sort(key=lambda c: (c["t_show"], c["layer"]))
    for i, cue in enumerate(cues, start=1):
        cue["cue_id"] = f"{MATCH_ID}-c{i:03d}"
        cue["match_id"] = MATCH_ID
        cue.setdefault("moment_id", goal["moment_id"] if cue["t_show"] < card["t_start"]
                       else card["moment_id"])  # fmt: skip
        Cue.model_validate(cue)
    track = {"schema_version": SCHEMA_VERSION, "match_id": MATCH_ID, "languages": ["en", "es"],
             "cues": cues}  # fmt: skip
    return CueTrack.model_validate(track).model_dump(mode="json", exclude_none=True)


# ---------------------------------------------------------------------------------------


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build(out: Path) -> None:
    rng = random.Random(17)
    league = build_league(rng)
    season = build_season(rng, league)
    meta = build_meta(league)
    events = build_events()
    frames = build_frames(meta, league)
    moments = build_moments(frames, season, league)
    cues = build_cues(moments)

    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "league.json", league.model_dump(mode="json"))
    _write_json(out / "season.json", season.model_dump(mode="json", exclude_none=True))
    _write_json(out / "match.json", meta.model_dump(mode="json"))
    _write_json(out / "events.json", events)
    _write_json(out / "moments.json", moments)
    _write_json(out / "cues.json", cues)
    with (out / "frames.jsonl").open("w", encoding="utf-8") as fh:
        for frame in frames:
            fh.write(json.dumps(frame, separators=(",", ":")) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    build(args.out)
    print(f"Wrote sample match {MATCH_ID} to {args.out}")


if __name__ == "__main__":
    main()
