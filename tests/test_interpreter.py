import asyncio
import json
from pathlib import Path
from typing import Any

from matchlens.agents.crew import explain_match
from matchlens.agents.interpreter import InterpretJob, check_lines, interpret, interpret_cards
from matchlens.agents.runners import OfflineRunner, Usage
from matchlens.explain.director import direct
from matchlens.explain.match import load
from matchlens.gen import generate_match
from matchlens.gen.cli import write_one


def _md(tmp: Path, home: str, away: str, seed: int) -> Any:
    m = generate_match(home, away, seed)
    return load(
        write_one(tmp, m.match_id, m.home, m.away, seed, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes)
    )


class Says:
    """A stand-in model that always gives the same answer."""

    name = "scripted"

    def __init__(self, answer: dict[str, str]) -> None:
        self.answer = answer
        self.usage = Usage()
        self.calls = 0

    async def run(self, role: Any, prompt: str, tools: Any, job: Any) -> str:
        self.calls += 1
        return json.dumps(self.answer)

    async def close(self) -> None:
        return None


def _card(tmp: Path) -> tuple[Any, dict[str, Any]]:
    md = _md(tmp, "ash", "brk", 31)
    cards = direct(explain_match(md, "offline")["cards"])
    return md, next(c for c in cards if c["cause"]["kind"] == "play_change")


def test_the_rules_lines_pass_the_check_and_read_as_insight(tmp_path: Path) -> None:
    md, card = _card(tmp_path)
    job = InterpretJob(card["facts"], set())
    assert check_lines(job, card["text"]) == []
    assert set(card["text"]) == {"neutral", *md.teams}


def test_the_check_holds_the_lines_to_the_facts(tmp_path: Path) -> None:
    md, card = _card(tmp_path)
    home, away = md.teams
    job = InterpretJob(card["facts"], {"Nobody"})
    good = dict(card["text"])
    bad = {
        "neutral": f"The manager has told {md.short(home)} to push 3 men forward.",
        home: good[home],
        away: f"Nobody is running the show against {md.short(away)}.",
    }
    problems = " ".join(check_lines(job, bad))
    assert "number" in problems and "manager" in problems and "names Nobody" in problems


def test_a_rejected_draft_goes_back_once_then_falls_back(tmp_path: Path) -> None:
    md, card = _card(tmp_path)
    home, away = md.teams
    runner = Says({"neutral": "The manager changed it.", home: "x", away: "y"})
    lines, fallback = asyncio.run(interpret(runner, InterpretJob(card["facts"], set())))
    assert fallback and runner.calls == 2 and lines == card["text"]


def test_interpreted_cards_carry_the_log(tmp_path: Path) -> None:
    md, card = _card(tmp_path)
    asyncio.run(interpret_cards(OfflineRunner(), md, [card]))
    log = card["agents"]["interpreter"]
    assert not log["fallback"] and [r["status"] for r in log["rounds"]] == ["passed"]
