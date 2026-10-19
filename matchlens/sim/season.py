"""The season generator: every match before the streamed one, played on the same engine.

It builds a double round robin for the league, plays matchdays 1 to N-1 headless (events
and movement, no frames), and adds up the table, form, player season stats and
discipline. Suspensions carry forward: a player who reaches the yellow-card threshold or
is sent off misses his team's next match(es), including the streamed one, and the
season file says which match ids he is banned from.

Matches on one matchday are independent, so they run in parallel; the result does not
depend on the number of workers.
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from matchlens.contracts import SCHEMA_VERSION, League, Season, WinProbability

from .calibration import match_stats
from .engine import TICKS_PER_S, MatchEngine
from .league import LEAGUE_ID
from .match import SEASON_ID
from .models import pre_match_win_probability
from .render import movement_summary

PASS_TYPES = ("pass", "throw_in", "goal_kick", "free_kick", "corner", "kick_off")
STRAIGHT_RED_BAN = 3
SECOND_YELLOW_BAN = 1


@dataclass(frozen=True)
class Fixture:
    match_id: str
    matchday: int
    home: str
    away: str


def match_seed(season_seed: int, match_id: str) -> int:
    """A match's seed, derived from the season seed so every match is reproducible alone."""
    return (season_seed * 1_000_003 + int(match_id[1:]) * 7_919) % 2**31


def build_schedule(
    team_ids: list[str], seed: int, featured: tuple[str, str], featured_matchday: int
) -> list[Fixture]:
    """Double round robin by the circle method, with ``featured`` on ``featured_matchday``."""
    rng = random.Random(seed)
    teams = list(team_ids)
    rng.shuffle(teams)
    n = len(teams)
    rounds: list[list[tuple[str, str]]] = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = teams[i], teams[n - 1 - i]
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        rounds.append(pairs)
        teams = [teams[0], teams[-1], *teams[1:-1]]
    rounds += [[(b, a) for a, b in pairs] for pairs in rounds]
    # Move the round holding the featured fixture to the featured matchday.
    where = next(i for i, pairs in enumerate(rounds) if featured in pairs)
    target = featured_matchday - 1
    rounds[where], rounds[target] = rounds[target], rounds[where]
    fixtures: list[Fixture] = []
    for md, pairs in enumerate(rounds, start=1):
        for home, away in sorted(pairs, key=lambda p: (p != featured, p)):
            fixtures.append(Fixture(f"m{len(fixtures) + 1:03d}", md, home, away))
    return fixtures


# --------------------------------------------------------------------------------------
# One headless match, run in a worker process
# --------------------------------------------------------------------------------------

_LEAGUE: League | None = None


def _init_worker(league_json: str) -> None:
    global _LEAGUE
    _LEAGUE = League.model_validate_json(league_json)


def _play(args: tuple[Fixture, int, frozenset[str]]) -> dict[str, Any]:
    fixture, seed, unavailable = args
    assert _LEAGUE is not None
    return play_headless(_LEAGUE, fixture, seed, unavailable)


def play_headless(
    league: League, fixture: Fixture, seed: int, unavailable: frozenset[str]
) -> dict[str, Any]:
    """Play a match without rendering frames; return what the season needs from it."""
    result = MatchEngine(
        league, fixture.home, fixture.away, fixture.match_id, seed, unavailable=unavailable
    ).run()
    moves = movement_summary(result)
    players: dict[str, dict[str, Any]] = {}
    for p in result.players:
        off = p.t_off if p.t_off is not None else result.end_tick
        distance, top = moves[p.pid]
        players[p.pid] = {
            "team_id": fixture.home if p.side == 0 else fixture.away,
            "minutes": round((off - p.t_on) / TICKS_PER_S / 60),
            "distance_m": distance,
            "top_speed_kmh": top,
            "goals": 0, "assists": 0, "shots": 0, "passes": 0, "complete": 0,
            "difficulty": [], "yellow": 0, "second_yellow": 0, "red": 0,
        }  # fmt: skip
    for e in result.events:
        pid = e.get("player_id")
        if pid not in players:
            continue
        s = players[pid]
        q = e.get("qualifiers", {})
        et = e["type"]
        if et in PASS_TYPES:
            s["passes"] += 1
            s["complete"] += e.get("outcome") == "complete"
            if "difficulty" in q:
                s["difficulty"].append(q["difficulty"])
        elif et == "shot":
            s["shots"] += 1
        elif et == "goal":
            s["goals"] += 1
            if q.get("assist_player_id") in players:
                players[q["assist_player_id"]]["assists"] += 1
        elif et == "card":
            s[
                {"yellow": "yellow", "second_yellow": "second_yellow", "red": "red"}[e["outcome"]]
            ] += 1
    stats = match_stats(result.events)
    return {
        "fixture": fixture,
        "score": result.score,
        "players": players,
        "team_stats": stats.values,
    }


# --------------------------------------------------------------------------------------
# The season
# --------------------------------------------------------------------------------------


@dataclass
class SeasonResult:
    season: Season
    fixtures: list[Fixture]
    results: list[dict[str, Any]] = field(repr=False)
    featured: Fixture

    @property
    def featured_unavailable(self) -> frozenset[str]:
        return frozenset(
            p.player_id for p in self.season.players if self.featured.match_id in p.suspended_for
        )


def generate_season(
    league: League,
    seed: int = 2026,
    featured: tuple[str, str] = ("ash", "brk"),
    featured_matchday: int = 30,
    workers: int = 1,
) -> SeasonResult:
    """Play every matchday before ``featured_matchday`` and build ``season.json``."""
    team_ids = [c.team_id for c in league.clubs]
    fixtures = build_schedule(team_ids, seed, featured, featured_matchday)
    featured_fx = next(
        f for f in fixtures if f.matchday == featured_matchday and (f.home, f.away) == featured
    )
    acc = _Accumulator(league)
    results: list[dict[str, Any]] = []
    pool = (
        ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(league.model_dump_json(),))
        if workers > 1
        else None
    )
    try:
        for md in range(1, featured_matchday):
            todays = [f for f in fixtures if f.matchday == md]
            jobs = [(f, match_seed(seed, f.match_id), acc.unavailable(f)) for f in todays]
            if pool is not None:
                played = list(pool.map(_play, jobs))
            else:
                played = [play_headless(league, *job) for job in jobs]
            for res in played:
                acc.add(res, md)
                results.append(res)
    finally:
        if pool is not None:
            pool.shutdown()
    season = acc.season(fixtures, featured_matchday, featured_fx)
    return SeasonResult(season, fixtures, results, featured_fx)


class _Accumulator:
    def __init__(self, league: League) -> None:
        self.league = league
        self.team_of = {p.player_id: c.team_id for c in league.clubs for p in c.squad}
        self.rows: dict[str, dict[str, Any]] = {
            c.team_id: {"team_id": c.team_id, "played": 0, "won": 0, "drawn": 0, "lost": 0,
                        "goals_for": 0, "goals_against": 0, "points": 0, "form": []}
            for c in league.clubs
        }  # fmt: skip
        self.players: dict[str, dict[str, Any]] = {
            pid: {"appearances": 0, "minutes": 0, "goals": 0, "assists": 0, "shots": 0,
                  "passes": 0, "complete": 0, "difficulty_sum": 0.0, "difficulty_n": 0,
                  "top_speed_kmh": 0.0, "distance_km": 0.0, "yellow_cards": 0,
                  "red_cards": 0, "last_goal_matchday": None}
            for pid in self.team_of
        }  # fmt: skip
        self.scores: dict[str, tuple[int, int]] = {}
        self.bans: dict[str, int] = defaultdict(int)
        """Matches still to serve, per player."""

    def unavailable(self, fixture: Fixture) -> frozenset[str]:
        return frozenset(
            pid
            for pid, n in self.bans.items()
            if n > 0 and self.team_of[pid] in (fixture.home, fixture.away)
        )

    def add(self, res: dict[str, Any], matchday: int) -> None:
        fx: Fixture = res["fixture"]
        hg, ag = res["score"]
        self.scores[fx.match_id] = (hg, ag)
        # Bans are served by sitting this match out.
        for pid in self.unavailable(fx):
            self.bans[pid] -= 1
        for team, gf, ga in ((fx.home, hg, ag), (fx.away, ag, hg)):
            row = self.rows[team]
            row["played"] += 1
            row["goals_for"] += gf
            row["goals_against"] += ga
            result = "W" if gf > ga else "L" if gf < ga else "D"
            row[{"W": "won", "D": "drawn", "L": "lost"}[result]] += 1
            row["points"] += {"W": 3, "D": 1, "L": 0}[result]
            row["form"] = [*row["form"], result][-5:]
        for pid, m in res["players"].items():
            s = self.players[pid]
            s["appearances"] += 1
            s["minutes"] += m["minutes"]
            for key in ("goals", "assists", "shots", "passes", "complete"):
                s[key] += m[key]
            s["difficulty_sum"] += sum(m["difficulty"])
            s["difficulty_n"] += len(m["difficulty"])
            s["top_speed_kmh"] = max(s["top_speed_kmh"], m["top_speed_kmh"])
            s["distance_km"] += m["distance_m"] / 1000
            if m["goals"]:
                s["last_goal_matchday"] = matchday
            if m["red"]:
                s["red_cards"] += 1
                self.bans[pid] += STRAIGHT_RED_BAN
            elif m["second_yellow"]:
                s["red_cards"] += 1
                self.bans[pid] += SECOND_YELLOW_BAN
            elif m["yellow"]:
                s["yellow_cards"] += 1
                if s["yellow_cards"] >= 5:
                    # The threshold triggers a ban and the count starts again.
                    s["yellow_cards"] = 0
                    self.bans[pid] += 1

    def season(self, fixtures: list[Fixture], featured_matchday: int, featured: Fixture) -> Season:
        ordered = sorted(
            self.rows.values(),
            key=lambda r: (
                -r["points"],
                -(r["goals_for"] - r["goals_against"]),
                -r["goals_for"],
                r["team_id"],
            ),
        )
        table = [
            {**r, "position": i, "goal_difference": r["goals_for"] - r["goals_against"]}
            for i, r in enumerate(ordered, start=1)
        ]
        upcoming: dict[str, list[str]] = defaultdict(list)
        for f in fixtures:
            if f.matchday >= featured_matchday:
                upcoming[f.home].append(f.match_id)
                upcoming[f.away].append(f.match_id)
        fixture_rows = []
        for f in fixtures:
            row: dict[str, Any] = {"match_id": f.match_id, "matchday": f.matchday,
                                   "home_id": f.home, "away_id": f.away}  # fmt: skip
            if f.matchday < featured_matchday:
                row["status"] = "played"
                home_goals, away_goals = self.scores[f.match_id]
                row["score"] = {"home": home_goals, "away": away_goals}
            else:
                row["status"] = "live" if f == featured else "scheduled"
            fixture_rows.append(row)
        players = []
        for pid, s in self.players.items():
            team = self.team_of[pid]
            ban = max(0, self.bans.get(pid, 0))
            players.append(
                {
                    "player_id": pid,
                    "team_id": team,
                    "appearances": s["appearances"],
                    "minutes": s["minutes"],
                    "goals": s["goals"],
                    "assists": s["assists"],
                    "shots": s["shots"],
                    "passes": s["passes"],
                    "pass_accuracy": round(s["complete"] / s["passes"], 3) if s["passes"] else None,
                    "avg_pass_difficulty": (
                        round(s["difficulty_sum"] / s["difficulty_n"], 3)
                        if s["difficulty_n"]
                        else None
                    ),
                    "top_speed_kmh": round(s["top_speed_kmh"], 1) or None,
                    "distance_km": round(s["distance_km"], 1),
                    "yellow_cards": s["yellow_cards"],
                    "red_cards": s["red_cards"],
                    "last_goal_matchday": s["last_goal_matchday"],
                    "suspended_for": upcoming[team][:ban],
                }
            )
        return Season.model_validate(
            {
                "schema_version": SCHEMA_VERSION,
                "league_id": LEAGUE_ID,
                "season_id": SEASON_ID,
                "through_matchday": featured_matchday - 1,
                "table": table,
                "fixtures": fixture_rows,
                "players": players,
            }
        )


def featured_context(
    league: League, season: Season, home_id: str, away_id: str
) -> tuple[list[str], WinProbability]:
    """Plain-fact stakes notes and a form-adjusted pre-match win probability."""
    clubs = {c.team_id: c for c in league.clubs}
    rows = {r.team_id: r for r in season.table}
    notes = []
    leader = season.table[0]
    for tid in (home_id, away_id):
        r = rows[tid]
        notes.append(f"{clubs[tid].short_name} are {_ordinal(r.position)} on {r.points} points")
        if r.position > 1 and r.points + 3 > leader.points:
            notes.append(f"A win would take {clubs[tid].short_name} top")
        elif r.position == 1 and r.points - season.table[1].points < 3:
            notes.append(f"A win keeps {clubs[tid].short_name} top")
    if away_id in clubs[home_id].rival_ids:
        notes.append("Local derby")
    threshold = season.rules.yellow_card_ban_threshold
    names = {p.player_id: p.short_name for c in league.clubs for p in c.squad}
    for p in season.players:
        club = clubs[p.team_id].short_name
        if p.team_id in (home_id, away_id) and p.yellow_cards == threshold - 1:
            notes.append(f"{names[p.player_id]} ({club}) is one booking from a ban")
        if p.team_id in (home_id, away_id) and p.suspended_for[:1] == [
            _match_id(season, home_id, away_id)
        ]:
            notes.append(f"{names[p.player_id]} ({club}) is suspended")

    def strength(tid: str) -> float:
        r = rows[tid]
        ppg = r.points / r.played if r.played else 1.4
        return clubs[tid].rating + 3.0 * (ppg - 1.4)

    return notes, pre_match_win_probability(strength(home_id), strength(away_id))


def _match_id(season: Season, home_id: str, away_id: str) -> str | None:
    for f in season.fixtures:
        if f.status != "played" and (f.home_id, f.away_id) == (home_id, away_id):
            return f.match_id
    return None


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def write_results_csv(results: list[dict[str, Any]], path: Path) -> None:
    """One row per played match: score and the headline team-level stats."""
    keys = ["goals", "shots", "shots_on_target", "xg", "passes", "pass_accuracy", "corners",
            "fouls", "yellow_cards", "red_cards", "offsides", "ball_in_play_min"]  # fmt: skip
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["match_id", "matchday", "home_id", "away_id", "home_goals", "away_goals", *keys]
        )
        for r in results:
            f: Fixture = r["fixture"]
            ts = r["team_stats"]
            w.writerow([f.match_id, f.matchday, f.home, f.away, *r["score"],
                        *[round(ts.get(k, 0.0), 3) for k in keys]])  # fmt: skip
