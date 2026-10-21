import asyncio
import json
from pathlib import Path

import pytest

from matchlens.explain.director import Director, direct
from matchlens.explain.explainer import explain_match
from matchlens.explain.match import load
from matchlens.gen import generate_match
from matchlens.gen.cli import write_one
from matchlens.ingest import unseen
from matchlens.ingest.feed import LiveMatch, export_feed, load_mapping, read_feed
from matchlens.ingest.runner import play


def _write(tmp: Path, home: str, away: str, seed: int) -> Path:
    m = generate_match(home, away, seed)
    return write_one(tmp, m.match_id, m.home, m.away, seed, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes)


def test_feed_carries_no_result_and_only_renamed_tables(tmp_path: Path) -> None:
    feed = export_feed(_write(tmp_path, "ash", "brk", 12), tmp_path / "feed")
    assert sorted(p.name for p in feed.iterdir()) == ["club_minutes.csv", "events.csv", "lineups.json", "player_minutes.csv"]
    lineup = json.loads((feed / "lineups.json").read_text())
    assert "final_score" not in lineup and "seed" not in lineup
    header = (feed / "club_minutes.csv").read_text().splitlines()[0].split(",")
    assert "Tick" in header and "passes" not in header and "GoalsForBefore" not in header
    kinds = {line.split(",")[4] for line in (feed / "events.csv").read_text().splitlines()[1:]}
    assert kinds <= set(load_mapping()["kinds"])


def test_live_feed_gives_the_same_match_and_cards_as_the_folder(tmp_path: Path) -> None:
    folder = _write(tmp_path, "cal", "dun", 5)
    feed = read_feed(export_feed(folder, tmp_path / "feed"))
    live = asyncio.run(play(feed.meta, feed.minutes))
    ref = load(folder)
    assert unseen.same_tables(live.match.md, ref) == []
    assert not live.match.missing
    one_go = explain_match(ref)
    shown = direct(one_go["cards"])  # marks the cards it puts up, as the live Director did
    assert json.dumps(live.cards, sort_keys=True) == json.dumps(one_go["cards"], sort_keys=True)
    assert [c["at"] for c in live.shown] == [c["at"] for c in shown]
    assert live.result()["momentum"] == one_go["momentum"]


def test_minutes_must_arrive_in_order(tmp_path: Path) -> None:
    feed = read_feed(export_feed(_write(tmp_path, "brk", "ash", 3), tmp_path / "feed"))
    match = LiveMatch(feed.meta)
    match.add(feed.minutes[0])
    with pytest.raises(ValueError):
        match.add(feed.minutes[2])


def test_missing_columns_are_reported(tmp_path: Path) -> None:
    feed = read_feed(export_feed(_write(tmp_path, "dun", "cal", 4), tmp_path / "feed"))
    match = LiveMatch(feed.meta)
    first = feed.minutes[0]
    for row in first.team.values():
        row.pop("sprints")
    match.add(first)
    assert "sprints" in match.missing


def _card(at: int, salience: float, kind: str = "play_change", mode: str = "shift") -> dict:
    return {"at": at, "salience": salience, "show": True, "stats": [{}], "mode": mode, "cause": {"kind": kind}}


def test_director_never_waits_for_a_better_card() -> None:
    d = Director()
    assert d.offer([_card(30, 0.5)])  # nothing on screen: it goes up now
    assert not d.offer([_card(32, 2.0)])  # better, but inside the cooldown
    assert d.offer([_card(33, 0.4, "chasing_the_game", "event")])  # urgent cards break the cooldown
    assert not d.offer([_card(33, 0.9, "goal_lift", "event")])  # but not twice in one minute
    assert d.offer([_card(38, 0.3), _card(38, 0.8)])[0]["salience"] == 0.8  # same minute: the best goes first


def test_unseen_matches_quick() -> None:
    report = unseen.run(matches=3, seed=77)
    assert report["passed"], [r["problems"] for r in report["per_match"]]
    assert report["numbers_checked"] > 0
