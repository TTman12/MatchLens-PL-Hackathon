import csv
import json
from pathlib import Path

from swing.data.io import read_match
from swing.gen import generate_match
from swing.gen.cli import write_one


def test_same_seed_same_match() -> None:
    a = generate_match("ash", "brk", 3)
    b = generate_match("ash", "brk", 3)
    assert a.events == b.events
    assert a.manager.decisions == b.manager.decisions


def test_match_is_plausible() -> None:
    m = generate_match("cal", "ash", 11)
    passes = [e for e in m.events if e["type"] == "pass"]
    assert 500 < len(passes) < 1300
    assert m.events[1].get("kick_off")
    goals = [e for e in m.events if e["type"] == "shot" and e["outcome"] == "goal"]
    assert len(goals) == m.home.score + m.away.score
    for period in (1, 2):
        ts = [e["t"] for e in m.events if e["period"] == period]
        assert ts == sorted(ts)
    duels = [e for e in m.events if e["type"] == "duel"]
    by_id: dict[str, list[str]] = {}
    for d in duels:
        by_id.setdefault(d["duel_id"], []).append(d["outcome"])
    assert all(sorted(v) in (["lost", "won"], ["neutral", "neutral"]) for v in by_id.values())


def test_never_more_than_eleven_on_the_pitch() -> None:
    m = generate_match("brk", "cal", 5)
    for team in (m.home, m.away):
        assert team.count <= 11
        subs = [e for e in m.events if e["type"] == "substitution" and e["team_id"] == team.team_id]
        assert len(subs) <= 3


def test_written_match_tables_agree(tmp_path: Path) -> None:
    m = generate_match("ash", "cal", 9)
    folder = write_one(tmp_path, m.match_id, m.home, m.away, 9, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes)
    assert not (folder / "truth.json").exists() and (tmp_path / "truth" / f"{m.match_id}.json").exists()
    meta, events, physical = read_match(folder)
    assert meta["final_score"] == [m.home.score, m.away.score]
    team = list(csv.DictReader((folder / "team_minute.csv").open()))
    player = list(csv.DictReader((folder / "player_minute.csv").open()))
    for col in ("passes", "duels", "shots"):
        assert sum(int(r[col]) for r in team) == sum(int(r[col]) for r in player)
    assert abs(sum(float(r["distance_m"]) for r in team) - sum(float(r["distance_m"]) for r in physical)) < 1
    truth = json.loads((tmp_path / "truth" / f"{m.match_id}.json").read_text())
    assert any(d["kind"] == "substitution" for d in truth["decisions"])
