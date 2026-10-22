from pathlib import Path
from typing import Any

from swing.broadcast.bundle import build
from swing.broadcast.tables import PLAYER_STATS, TEAM_STATS
from swing.explain import explainer
from swing.explain.match import load
from swing.explain.metrics import METRICS
from swing.explain.stories import BY_KEY, SHARES, compose, find_stories, match_story
from swing.gen import generate_match
from swing.gen.cli import write_one


def _write(tmp: Path, home: str, away: str, seed: int) -> Path:
    m = generate_match(home, away, seed)
    return write_one(tmp, m.match_id, m.home, m.away, seed, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes)


def _f(team: str, metric: str, effect: float, before: float = 10, after: float = 20) -> dict[str, Any]:
    return {"team": team, "metric": metric, "label": metric, "effect_sd": effect, "before": before, "after": after, "unit": "%"}


def test_a_story_needs_both_stats_to_move_its_way() -> None:
    deep = [_f("brk", "defending_height", -2.0, 45, 30), _f("brk", "clearances", 1.6, 2, 6)]
    found = find_stories(deep, gainer="ash")
    assert found[0]["key"] == "sitting_deep" and found[0]["aligned"]
    assert match_story(found[0]["stats"]) == "sitting_deep"
    # one stat moving the other way breaks the story
    assert not find_stories([deep[0], _f("brk", "clearances", -1.6, 6, 2)], gainer="ash")
    # both stats moving, but neither clearly, is not enough
    assert not find_stories([_f("brk", "defending_height", -1.2), _f("brk", "clearances", 1.2)], gainer="ash")


def test_the_sentence_is_written_for_each_club(tmp_path: Path) -> None:
    md = load(_write(tmp_path, "ash", "brk", 3))
    stats = [_f("brk", "defending_height", -2.0, 45, 30), _f("brk", "clearances", 1.6, 2, 6)]
    text = compose(md, {"kind": "play_change", "team": "ash"}, stats, "ash")
    assert set(text) == {"neutral", "ash", "brk"}
    assert text["brk"] == BY_KEY["sitting_deep"].own.format(T=md.short("brk"), O=md.short("ash"))
    assert "which is why" not in " ".join(text.values())  # what the play style is, not what it caused


def test_cards_never_show_a_share_alone_and_all_have_text(tmp_path: Path) -> None:
    stories = 0
    share_labels = {m.label for m in METRICS if m.key in SHARES}
    for seed, (h, a) in enumerate([("ash", "brk"), ("cal", "dun"), ("dun", "ash"), ("brk", "cal")]):
        md = load(_write(tmp_path, h, a, 60 + seed))
        for c in explainer.explain_match(md)["cards"]:
            team_stats = [s for s in c["stats"] if not s.get("player")]
            assert not (len(c["stats"]) == 1 and team_stats and c["stats"][0]["label"] in share_labels)
            assert set(c["text"]) == {"neutral", *md.teams}
            if c["stats"] or c["cause"]["kind"].endswith("no_change") or c["cause"]["kind"] == "goal_no_reaction":
                assert c["text"]["neutral"]
            stories += c["story"] is not None
    assert stories  # some cards in four matches tell a play-style story


def test_bundle_carries_running_stats(tmp_path: Path) -> None:
    md = load(_write(tmp_path, "cal", "ash", 8))
    b = build(md)
    st = b["stats"]
    n = md.last_minute + 1
    assert [d["key"] for d in st["team_stats"]] == [k for k, *_ in TEAM_STATS]
    assert [d["key"] for d in st["player_stats"]] == [k for k, *_ in PLAYER_STATS]
    for t, score in zip(md.teams, b["score"][-1], strict=True):
        goals = st["teams"][t]["goals"]
        assert len(goals) == n and goals == sorted(goals)  # running totals never go down
        assert goals[-1] == score
    poss = [st["teams"][t]["possession"][-1] for t in md.teams]
    assert abs(sum(poss) - 100) <= 1
    for p in st["players"]:
        assert p["stats"]["minutes"][-1] == len(md.player[p["id"]])


def test_a_standout_player_is_named_with_what_he_does_more(tmp_path: Path) -> None:
    md = load(_write(tmp_path, "dun", "cal", 4))
    p = {**_f("dun", "defensive_actions", 4.0, 1, 5), "claim": "player_change", "player": "x", "name": "Wexez"}
    q = {**_f("dun", "distance_m", 3.8, 110, 125), "claim": "player_change", "player": "y", "name": "Pennholt"}
    text = compose(md, {"kind": "play_change", "team": "dun"}, [p, q], "dun")
    assert text["neutral"] == "Wexez is making more tackles, and Pennholt is covering more ground."
    team = _f("dun", "high_turnovers", 2.0, 1, 4)
    mixed = compose(md, {"kind": "play_change", "team": "dun"}, [p, team], "dun")["neutral"]
    assert mixed.startswith("Wexez is making more tackles.") and md.short("dun") in mixed
