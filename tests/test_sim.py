"""The simulator: determinism, contract validity, physical sanity and football realism."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from matchlens.contracts import FRAME_RATE_HZ, Frame, League, MatchEvent, MatchMeta, Season
from matchlens.sim.calibration import match_stats
from matchlens.sim.engine import MatchEngine
from matchlens.sim.league import build_league
from matchlens.sim.match import SimulatedMatch, simulate_match, write_match
from matchlens.sim.models import expected_goals, pre_match_win_probability
from matchlens.sim.season import (
    Fixture,
    _Accumulator,
    build_schedule,
    featured_context,
    generate_season,
)
from matchlens.sim.storyline import STORYLINES

from .conftest import SAMPLE, SCHEMAS, load_json


@pytest.fixture(scope="module")
def league() -> League:
    return build_league()


@pytest.fixture(scope="module")
def match(league: League) -> SimulatedMatch:
    return simulate_match(league, "ash", "brk", "m001", seed=1325)


@pytest.fixture(scope="module")
def frames(match: SimulatedMatch) -> list[dict[str, Any]]:
    return list(match.iter_frames())


# --------------------------------------------------------------------------------------
# The league
# --------------------------------------------------------------------------------------


def test_league_is_twenty_fictional_clubs(league: League) -> None:
    assert len(league.clubs) == 20
    assert len({c.team_id for c in league.clubs}) == 20
    for club in league.clubs:
        assert len(club.squad) == 18
        assert {p.shirt for p in club.squad} == set(range(1, 19))
    # Name tags show the short name, so every one is unique across the league.
    short_names = [p.short_name for c in league.clubs for p in c.squad]
    assert len(short_names) == len(set(short_names))


def test_league_keeps_the_sample_story(league: League) -> None:
    """Clubs and named players from data/sample are the same in the simulated league."""
    sample = League.model_validate(load_json(SAMPLE / "league.json"))
    ours = {c.team_id: c for c in league.clubs}
    for club in sample.clubs:
        assert ours[club.team_id].name == club.name
        assert ours[club.team_id].stadium == club.stadium
    players = {p.player_id: p for c in league.clubs for p in c.squad}
    assert players["ash-09"].name == "Idris Varrow"
    assert players["ash-03"].attributes.discipline == 38


def test_league_is_reproducible() -> None:
    assert build_league(7).model_dump() == build_league(7).model_dump()


# --------------------------------------------------------------------------------------
# One match: files, determinism, consistency
# --------------------------------------------------------------------------------------


def test_same_seed_gives_the_same_match(league: League, match: SimulatedMatch) -> None:
    again = simulate_match(league, "ash", "brk", "m001", seed=1325)
    assert again.meta == match.meta
    assert again.events == match.events
    first = [f for _, f in zip(range(600), match.iter_frames(), strict=False)]
    second = [f for _, f in zip(range(600), again.iter_frames(), strict=False)]
    assert first == second


def test_different_seeds_give_different_matches(league: League, match: SimulatedMatch) -> None:
    other = simulate_match(league, "ash", "brk", "m001", seed=1326)
    assert [e.t for e in other.events[:50]] != [e.t for e in match.events[:50]]


def test_written_files_validate_against_the_json_schemas(
    match: SimulatedMatch, tmp_path: Path
) -> None:
    paths = write_match(match, tmp_path)
    MatchMeta.model_validate(load_json(paths["match"]))
    meta_schema = Draft202012Validator(load_json(SCHEMAS / "match_meta.schema.json"))
    meta_schema.validate(load_json(paths["match"]))
    event_schema = Draft202012Validator(load_json(SCHEMAS / "match_event.schema.json"))
    for e in load_json(paths["events"]):
        event_schema.validate(e)
    frame_schema = Draft202012Validator(load_json(SCHEMAS / "frame.schema.json"))
    with paths["frames"].open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i % 97 == 0:
                frame_schema.validate(json.loads(line))


def test_events_are_ordered_and_consistent(match: SimulatedMatch) -> None:
    events = match.events
    assert [e.event_id for e in events] == [f"m001-e{i:04d}" for i in range(1, len(events) + 1)]
    assert all(a.t <= b.t for a, b in pairwise(events))
    assert [e.type for e in events if e.type in ("period_start", "period_end")] == [
        "period_start",
        "period_end",
        "period_start",
        "period_end",
    ]
    teams = {match.meta.home.team_id, match.meta.away.team_id}
    for i, e in enumerate(events):
        assert e.team_id is None or e.team_id in teams
        if e.player_id:
            assert e.player_id[:3] == e.team_id
        if e.type == "goal":
            shot = events[i - 1]
            assert shot.type == "shot" and shot.outcome == "goal" and shot.t == e.t
    goals = [e for e in events if e.type == "goal"]
    final = (goals[-1].qualifiers.score_home, goals[-1].qualifiers.score_away) if goals else (0, 0)
    assert final == match.engine.score


def test_players_in_events_are_on_the_pitch(match: SimulatedMatch) -> None:
    on = {e.player_id for side in (match.meta.home, match.meta.away) for e in side.starting}
    for e in match.events:
        if e.type == "substitution":
            assert e.player_id in on
            on.discard(e.player_id)
            on.add(e.related_player_id)  # type: ignore[arg-type]
        elif e.type == "card" and e.outcome in ("red", "second_yellow"):
            on.discard(e.player_id)
        elif e.player_id and e.type != "card":
            assert e.player_id in on, e


def test_pre_match_win_probability_favours_the_stronger_side() -> None:
    p = pre_match_win_probability(80, 62)
    assert p.home > 0.6 > p.away
    assert abs(p.home + p.draw + p.away - 1) < 1e-6
    even = pre_match_win_probability(70, 70)
    assert even.home > even.away  # home advantage
    assert 0.22 < even.draw < 0.32


def test_xg_falls_with_distance_and_angle() -> None:
    assert expected_goals(99, 34) > expected_goals(94, 34) > expected_goals(85, 34)
    assert expected_goals(94, 34) > expected_goals(94, 12)
    assert expected_goals(80, 34) < 0.06


# --------------------------------------------------------------------------------------
# Tracking frames: continuous and physically plausible
# --------------------------------------------------------------------------------------


def test_frames_are_continuous_at_10_hz(frames: list[dict[str, Any]]) -> None:
    times = [f["t"] for f in frames]
    assert times[0] == 0.0
    assert {round(b - a, 3) for a, b in pairwise(times)} == {1 / FRAME_RATE_HZ}
    for f in frames[::500]:
        Frame.model_validate(f)
        assert 18 <= len(f["players"]) <= 22


def test_players_never_outrun_themselves(
    league: League, match: SimulatedMatch, frames: list[dict[str, Any]]
) -> None:
    """Speeds in frames stay under each player's top speed, and positions don't jump."""
    top = {p.player_id: p.top_speed_kmh for c in league.clubs for p in c.squad}
    second_half = match.engine.period_starts[1] / 10
    fastest: dict[str, float] = Counter()
    for a, b in pairwise(frames):
        for pid, (x, y, vx, vy) in b["players"].items():
            assert -2.0 <= x <= 107.0 and -2.0 <= y <= 70.0  # a throw-in is taken off the pitch
            speed = math.hypot(vx, vy) * 3.6
            fastest[pid] = max(fastest[pid], speed)
            if pid in a["players"] and b["t"] != second_half:
                px, py = a["players"][pid][:2]
                assert math.hypot(x - px, y - py) < 1.2, (pid, b["t"])
    for pid, speed in fastest.items():
        assert speed <= top[pid] * 1.06 + 0.5, (pid, speed, top[pid])
    # Somebody sprints: the fastest player in the match is above 30 km/h.
    assert max(fastest.values()) > 30


def test_ball_moves_like_a_ball(frames: list[dict[str, Any]]) -> None:
    speeds = [
        math.dist(a["ball"][:2], b["ball"][:2]) * FRAME_RATE_HZ * 3.6 for a, b in pairwise(frames)
    ]
    assert max(speeds) < 135
    assert max(f["ball"][2] for f in frames) < 30
    assert min(f["ball"][2] for f in frames) >= 0.1


def test_distance_covered_is_realistic(match: SimulatedMatch, frames: list[dict[str, Any]]) -> None:
    """Outfield players who play the whole match cover roughly 8 to 13.5 km."""
    full = {
        p.pid
        for p in match.engine.players
        if p.t_on == 0 and p.t_off == match.engine.end_tick and p.group != "GK"
    }
    covered: dict[str, float] = Counter()
    cut = match.engine.period_starts[1] / 10
    for a, b in pairwise(frames):
        if b["t"] == cut:
            continue
        for pid in full:
            if pid in a["players"] and pid in b["players"]:
                covered[pid] += math.dist(a["players"][pid][:2], b["players"][pid][:2])
    km = sorted(v / 1000 for v in covered.values())
    assert 8.0 < statistics.median(km) < 12.5
    assert km[0] > 6.5 and km[-1] < 14.5


# --------------------------------------------------------------------------------------
# Football realism over many matches
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def many(league: League) -> list[dict[str, float]]:
    ids = [c.team_id for c in league.clubs]
    out = []
    for i in range(24):
        home, away = ids[i % 20], ids[(i * 7 + 3) % 20]
        if home == away:
            away = ids[(i + 1) % 20]
        result = MatchEngine(league, home, away, f"m{i + 1:03d}", 9000 + i).run()
        values = match_stats(result.events).values
        values["home_goals"], values["away_goals"] = result.score
        out.append(values)
    return out


# Looser than the calibration targets because 24 matches is a small sample.
@pytest.mark.parametrize(
    ("stat", "low", "high"),
    [
        ("goals", 1.8, 3.9),
        ("shots", 17, 32),
        ("shots_on_target", 5.5, 11.5),
        ("xg_per_shot", 0.08, 0.16),
        ("passes", 750, 1200),
        ("pass_accuracy", 0.74, 0.88),
        ("corners", 6, 14),
        ("fouls", 14, 28),
        ("yellow_cards", 2.0, 5.5),
        ("offsides", 1.5, 6.0),
        ("throw_ins", 25, 55),
        ("ball_in_play_min", 50, 66),
        ("match_length_min", 92, 103),
    ],
)
def test_per_match_averages_look_like_football(
    many: list[dict[str, float]], stat: str, low: float, high: float
) -> None:
    mean = statistics.fmean(m[stat] for m in many)
    assert low <= mean <= high, f"{stat} averaged {mean:.2f}, expected {low} to {high}"


def test_scorelines_vary(many: list[dict[str, float]]) -> None:
    results = Counter(
        "H"
        if m["home_goals"] > m["away_goals"]
        else "A"
        if m["away_goals"] > m["home_goals"]
        else "D"
        for m in many
    )
    assert results["H"] >= 5 and results["A"] >= 3 and results["D"] >= 2
    assert max(m["home_goals"] + m["away_goals"] for m in many) >= 4


# --------------------------------------------------------------------------------------
# Storylines
# --------------------------------------------------------------------------------------


def _key_moments(match: SimulatedMatch) -> list[tuple[float, str, str]]:
    return [
        (e.t / 60, e.type if e.type == "goal" else str(e.outcome), e.player_id or "")
        for e in match.events
        if e.type == "goal" or (e.type == "card" and e.outcome in ("red", "second_yellow"))
    ]


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_comeback_storyline_plays_out(league: League, seed: int) -> None:
    match = simulate_match(league, "ash", "brk", "m001", seed, storyline=STORYLINES["comeback"])
    assert match.engine.score == (3, 2)
    moments = _key_moments(match)
    assert [m[2][:3] for m in moments] == ["brk", "brk", "brk", "ash", "ash", "ash"]
    assert moments[2][1] in ("red", "second_yellow") and 56 <= moments[2][0] < 66
    winner = moments[-1]
    assert winner[2] == "ash-09" and winner[0] >= 90


def test_late_winner_storyline(league: League) -> None:
    match = simulate_match(league, "ash", "brk", "m001", 4, storyline=STORYLINES["late_winner"])
    assert match.engine.score == (2, 1)
    last = _key_moments(match)[-1]
    assert last[2] == "ash-09" and last[0] >= 88


def test_red_card_storyline_is_not_strict(league: League) -> None:
    match = simulate_match(league, "ash", "brk", "m001", 5, storyline=STORYLINES["red_card"])
    reds = [m for m in _key_moments(match) if m[1] == "red"]
    assert len(reds) == 1 and reds[0][2].startswith("brk") and 34 <= reds[0][0] < 42


# --------------------------------------------------------------------------------------
# The season
# --------------------------------------------------------------------------------------


def test_schedule_is_a_double_round_robin(league: League) -> None:
    ids = [c.team_id for c in league.clubs]
    fixtures = build_schedule(ids, 2026, ("ash", "brk"), 30)
    assert len(fixtures) == 380
    pairs = Counter((f.home, f.away) for f in fixtures)
    assert set(pairs.values()) == {1}
    assert all((b, a) in pairs for a, b in pairs)
    for md in range(1, 39):
        teams = [t for f in fixtures if f.matchday == md for t in (f.home, f.away)]
        assert sorted(teams) == sorted(ids)
    assert any(f.matchday == 30 and (f.home, f.away) == ("ash", "brk") for f in fixtures)


@pytest.fixture(scope="module")
def short_season(league: League) -> Any:
    return generate_season(league, seed=3, featured_matchday=3, workers=1)


def test_season_adds_up(short_season: Any) -> None:
    season: Season = short_season.season
    assert season.through_matchday == 2
    played = [f for f in season.fixtures if f.status == "played"]
    assert len(played) == 20
    assert sum(r.played for r in season.table) == 40
    assert sum(r.goals_for for r in season.table) == sum(
        f.score.home + f.score.away for f in played
    )
    assert sum(p.goals for p in season.players) == sum(r.goals_for for r in season.table)
    assert [r.position for r in season.table] == list(range(1, 21))
    assert all(a.points >= b.points for a, b in pairwise(season.table))
    live = [f for f in season.fixtures if f.status == "live"]
    assert [(f.home_id, f.away_id, f.matchday) for f in live] == [("ash", "brk", 3)]
    starters = [p for p in season.players if p.minutes >= 180 and not p.player_id.endswith("-01")]
    assert starters and all(28 < (p.top_speed_kmh or 0) < 37 for p in starters)
    assert all(15 < (p.distance_km or 0) < 27 for p in starters)


def test_featured_context_states_plain_facts(league: League, short_season: Any) -> None:
    notes, prob = featured_context(league, short_season.season, "ash", "brk")
    assert any("Ashmere are" in n for n in notes)
    assert "Local derby" in notes
    assert abs(prob.home + prob.draw + prob.away - 1) < 1e-6


def test_bans_follow_the_rules(league: League) -> None:
    acc = _Accumulator(league)
    fx = [Fixture(f"m{i:03d}", i, "ash", "brk") for i in range(1, 8)]

    def result(f: Fixture, cards: dict[str, str]) -> dict[str, Any]:
        players = {
            pid: {"team_id": pid[:3], "minutes": 90, "distance_m": 10000, "top_speed_kmh": 32,
                  "goals": 0, "assists": 0, "shots": 0, "passes": 0, "complete": 0,
                  "difficulty": [], "yellow": 0, "second_yellow": 0, "red": 0}
            for pid in ("ash-03", "brk-04")
            if pid not in acc.unavailable(f)
        }  # fmt: skip
        for pid, card in cards.items():
            if pid in players:
                players[pid][card] = 1
        return {"fixture": f, "score": (0, 0), "players": players, "team_stats": {}}

    # Five yellows trigger a one-match ban; a straight red, three.
    for i in range(5):
        acc.add(result(fx[i], {"ash-03": "yellow"}), i + 1)
    assert "ash-03" in acc.unavailable(fx[5])
    acc.add(result(fx[5], {"brk-04": "red"}), 6)
    assert "ash-03" not in acc.unavailable(fx[6])
    assert "brk-04" in acc.unavailable(fx[6])
    assert acc.bans["brk-04"] == 3
    assert acc.players["ash-03"]["yellow_cards"] == 0


def test_events_validate_as_contracts(match: SimulatedMatch) -> None:
    for e in match.events[:200]:
        MatchEvent.model_validate(e.model_dump())
