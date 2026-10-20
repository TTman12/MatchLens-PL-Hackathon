"""The simulator's events follow from one another, as they would in a real match.

A corner only follows the ball going behind off a defender, a goal kick only follows it
going behind off an attacker, a throw-in only follows it crossing a touchline, and a
free kick only follows a foul or an offside. Shots convert like real shots: most miss or
are saved, and long-range efforts rarely go in.
"""

from __future__ import annotations

import statistics
from typing import Any

import pytest

from matchlens.contracts import PITCH_LENGTH_M, PITCH_WIDTH_M, League
from matchlens.sim.engine import MatchEngine
from matchlens.sim.league import build_league
from matchlens.sim.storyline import STORYLINES

IGNORED = {"substitution", "card", "pressure"}
"""Events that can sit between the ball going out (or a foul) and the restart."""


@pytest.fixture(scope="module")
def league() -> League:
    return build_league()


@pytest.fixture(scope="module")
def matches(league: League) -> list[list[dict[str, Any]]]:
    ids = [c.team_id for c in league.clubs]
    out = []
    for i in range(10):
        home, away = ids[(i * 3) % 20], ids[(i * 3 + 7) % 20]
        out.append(MatchEngine(league, home, away, f"m{i + 1:03d}", 4400 + i).run().events)
    comeback = STORYLINES["comeback"]
    for seed in (0, 1):
        out.append(MatchEngine(league, "ash", "brk", "m900", seed, storyline=comeback).run().events)
    return out


def _in_frame(e: dict[str, Any], team: str, key: str = "end") -> tuple[float, float]:
    """An event's point in ``team``'s attacking frame (the frames are a 180 degree turn)."""
    x, y = e[key]
    if e["team_id"] == team:
        return (x, y)
    return (PITCH_LENGTH_M - x, PITCH_WIDTH_M - y)


def _went_out(e: dict[str, Any]) -> bool:
    q = e.get("qualifiers", {})
    return (
        e.get("outcome") == "out"
        or (e["type"] == "shot" and e.get("outcome") == "off_target")
        or bool(q.get("out_of_play"))
    )


def _cause(events: list[dict[str, Any]], i: int) -> dict[str, Any]:
    j = i - 1
    while events[j]["type"] in IGNORED:
        j -= 1
    return events[j]


def test_every_restart_has_a_cause(matches: list[list[dict[str, Any]]]) -> None:
    checked = 0
    for events in matches:
        for i, e in enumerate(events):
            kind = e["type"]
            if kind not in ("corner", "goal_kick", "throw_in", "free_kick", "kick_off"):
                if kind == "shot" and e.get("qualifiers", {}).get("penalty"):
                    assert _cause(events, i)["type"] == "foul", e
                continue
            cause = _cause(events, i)
            team = e["team_id"]
            checked += 1
            if kind == "kick_off":
                assert cause["type"] in ("period_start", "goal"), (e, cause)
                continue
            if kind == "free_kick":
                assert cause["type"] in ("foul", "offside"), (e, cause)
                assert cause["team_id"] != team, (e, cause)
                continue
            assert _went_out(cause), (e, cause)
            x, y = _in_frame(cause, team)
            if kind == "throw_in":
                assert cause["team_id"] != team, (e, cause)
                assert y <= 0.5 or y >= PITCH_WIDTH_M - 0.5, (e, cause)
                tx, _ = e["start"]
                assert abs(tx - x) < 1.5, (e, cause)
            elif kind == "corner":
                # Behind the goal the corner-taker attacks, last touched by a defender.
                assert cause["team_id"] != team, (e, cause)
                assert x >= PITCH_LENGTH_M - 0.5, (e, cause)
                assert e["start"][0] >= PITCH_LENGTH_M - 1.0, e
            else:
                # Behind the goal the goal-kick team defends, last touched by an attacker.
                assert cause["team_id"] != team, (e, cause)
                assert x <= 0.5, (e, cause)
    assert checked > 500


def test_the_ball_reaches_the_line_before_a_restart(league: League) -> None:
    """The ball is seen to go out: a flight ends on the line before the restart's still ball."""
    engine = MatchEngine(league, "ash", "brk", "m001", 1325)
    result = engine.run()
    segs = sorted(result.ball, key=lambda s: s.t0)
    restarts = [e for e in result.events if e["type"] in ("corner", "throw_in")]
    assert restarts
    for e in restarts:
        tick = round(e["t"] * 10)
        before = [s for s in segs if s.t1 <= tick and s.kind != "still"]
        ends = [s.p1 for s in before[-3:]]
        on_line = [
            p
            for p in ends
            if p[0] <= 0.6
            or p[0] >= PITCH_LENGTH_M - 0.6
            or p[1] <= 0.6
            or p[1] >= PITCH_WIDTH_M - 0.6
        ]
        assert on_line, (e, ends)


def test_shots_convert_like_real_shots(matches: list[list[dict[str, Any]]]) -> None:
    shots = [
        e
        for events in matches[:10]
        for e in events
        if e["type"] == "shot" and not e["qualifiers"].get("penalty")
    ]
    goals = [s for s in shots if s["outcome"] == "goal"]
    rate = len(goals) / len(shots)
    assert 0.06 <= rate <= 0.16, rate
    # Conversion follows xG: the goals come from better chances than the misses.
    assert statistics.fmean(s["qualifiers"]["xg"] for s in goals) > 2 * statistics.fmean(
        s["qualifiers"]["xg"] for s in shots if s["outcome"] != "goal"
    )
    long_range = [s for s in shots if s["qualifiers"]["distance_m"] > 25]
    assert len(long_range) / len(shots) < 0.25
    assert sum(s["outcome"] == "goal" for s in long_range) <= max(1, len(long_range) // 15)
    on_target = [s for s in shots if s["outcome"] in ("goal", "saved")]
    assert 0.25 <= len(on_target) / len(shots) <= 0.45


def test_scripted_goals_come_from_real_chances(matches: list[list[dict[str, Any]]]) -> None:
    for events in matches[10:]:
        goals = [e for e in events if e["type"] == "shot" and e["outcome"] == "goal"]
        assert len(goals) == 5
        for g in goals:
            assert g["qualifiers"]["xg"] >= 0.06, g
            assert g["qualifiers"]["distance_m"] <= 22, g


def test_keepers_stay_at_goal(league: League) -> None:
    engine = MatchEngine(league, "ash", "brk", "m001", 1325)
    result = engine.run()
    keepers = [p for p in result.players if p.group == "GK"]
    assert len(keepers) >= 2
    for k in keepers:
        xs = [x for t, x, _ in k.keyframes if t >= 0]
        # Each keeper spends the match within 20 m of a goal line (they swap ends at half-time).
        near_line = sum(1 for x in xs if min(x, PITCH_LENGTH_M - x) < 20) / len(xs)
        assert near_line > 0.9, near_line
