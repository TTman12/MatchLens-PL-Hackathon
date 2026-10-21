import asyncio
import json
from pathlib import Path
from typing import Any

from matchlens.agents.analyst import AnalystJob, analyse, analyse_cards, check_analysis
from matchlens.agents.crew import explain_match
from matchlens.agents.runners import OfflineRunner, Usage
from matchlens.explain.analysis import EXCLUSIVE, LEVERS, lenses, speaks_to
from matchlens.explain.director import direct
from matchlens.explain.insight import PLAYER_LINES
from matchlens.explain.match import load
from matchlens.gen import generate_match
from matchlens.gen.cli import write_one


def _cards(tmp: Path, home: str = "cal", away: str = "dun", seed: int = 32) -> tuple[Any, list[dict[str, Any]]]:
    m = generate_match(home, away, seed)
    md = load(write_one(tmp, m.match_id, m.home, m.away, seed, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes))
    return md, direct(explain_match(md, "offline")["cards"])


def _analysed(tmp: Path) -> tuple[Any, dict[str, Any]]:
    md, cards = _cards(tmp)
    return md, next(c for c in cards if len({o["team"] for o in c["analysis"]["facts"]["options"]}) == 2)


class Says:
    """A stand-in model that always gives the same answer."""

    name = "scripted"

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.usage = Usage()
        self.calls = 0

    async def run(self, role: Any, prompt: str, tools: Any, job: Any) -> str:
        self.calls += 1
        return json.dumps(self.answer)

    async def close(self) -> None:
        return None


def test_every_lever_line_argues_its_own_lever_and_nothing_else() -> None:
    for lv in LEVERS:
        specs = [lv.neutral, lv.fan]
        for line in [x for s in specs for x in ([s] if isinstance(s, str) else s.values())]:
            filled = line.format(T="Ashmere", O="Dunmoor")
            assert any(speaks_to(filled, t) for t in lv.topics), (lv.key, filled)
            assert not [t for t in EXCLUSIVE if t not in lv.topics and speaks_to(filled, t)], (lv.key, filled)


def test_a_lever_only_comes_up_when_a_stat_backs_it(tmp_path: Path) -> None:
    _, cards = _cards(tmp_path)
    by_key = {lv.key: lv for lv in LEVERS}
    for c in cards:
        for o in c["analysis"]["facts"]["options"]:
            lv = by_key[o["lever"]]
            ev = o["evidence"]
            assert ev["metric"] in lv.metrics
            moved = 1 if ev["after"] > ev["before"] else -1
            assert moved == lv.direction, (o["lever"], ev)
            assert (ev["team"] == o["team"]) == (lv.whose == "own")


def test_each_fan_hears_about_their_own_club_and_the_neutral_about_the_side_without_momentum(tmp_path: Path) -> None:
    md, card = _analysed(tmp_path)
    fx = card["analysis"]["facts"]
    who = lenses(fx, card["analysis"]["picks"])
    assert who["neutral"] == fx["momentum_against"]
    assert all(who[t] == t for t in md.teams)
    modes = {o["team"]: o["mode"] for o in fx["options"]}
    assert modes[fx["momentum_against"]] == "fix" and modes[fx["momentum_with"]] == "keep"


def test_the_rules_lines_pass_the_check(tmp_path: Path) -> None:
    md, cards = _cards(tmp_path)
    for c in cards:
        a = c["analysis"]
        if a["facts"]["options"]:
            job = AnalystJob(a["facts"], c["cause"]["kind"], set(md.names.values()))
            assert check_analysis(job, {"picks": a["picks"], **a["text"]}) == []


def test_the_check_holds_the_analyst_to_its_pick(tmp_path: Path) -> None:
    md, card = _analysed(tmp_path)
    a = card["analysis"]
    fx = a["facts"]
    lo, g = fx["momentum_against"], fx["momentum_with"]
    name = fx["teams"][lo]["name"]
    player = next(iter(md.names.values()))
    bad = {
        "picks": a["picks"],
        "neutral": f"The manager should tell {name} to go 2 up front.",
        lo: f"{name} should get {player} on the ball and play a higher line and press.",
        g: a["text"][g],
    }
    problems = " ".join(check_analysis(AnalystJob(fx, card["cause"]["kind"], set(md.names.values())), bad))
    assert "number" in problems and "manager" in problems and f"names {player}" in problems
    assert "'line'" in problems or "'press'" in problems  # whichever its pick doesn't cover
    wrong_team = {"picks": {lo: next(o["id"] for o in fx["options"] if o["team"] == g), g: a["picks"][g]}, **a["text"]}
    assert "not " + lo in " ".join(check_analysis(AnalystJob(fx, "play_change", set()), wrong_team))


def test_a_rejected_draft_goes_back_once_then_falls_back(tmp_path: Path) -> None:
    md, card = _analysed(tmp_path)
    a = card["analysis"]
    runner = Says({"picks": a["picks"], "neutral": "Sack the manager.", **{t: "x" for t in md.teams}})
    picks, text, fallback = asyncio.run(analyse(runner, AnalystJob(a["facts"], "play_change", set())))
    assert fallback and runner.calls == 2 and text == a["text"] and picks == a["picks"]


def test_analysed_cards_carry_the_log(tmp_path: Path) -> None:
    md, card = _analysed(tmp_path)
    asyncio.run(analyse_cards(OfflineRunner(), md, [card]))
    log = card["agents"]["analyst"]
    assert not log["fallback"] and [r["status"] for r in log["rounds"]] == ["passed"]


def test_player_cards_say_how_the_player_moves_the_game(tmp_path: Path) -> None:
    for home, away, seed in (("cal", "dun", 32), ("brk", "cal", 33)):
        md, cards = _cards(tmp_path, home, away, seed)
        for c in cards:
            star = next((s for s in c["facts"]["stats"] if s.get("player")), None)
            if star and c["facts"]["reading"]["key"] in ("player_drive", "fresh_legs") and star["metric"] in PLAYER_LINES:
                other = next(t for t in md.teams if t != star["team"])
                # the line names the player and says what it does to the other side, not just what he does more of
                assert star["player"] in c["text"]["neutral"] and md.short(other) in c["text"]["neutral"]
                assert "meaning" in star
