import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from swing.agents.crew import explain_match
from swing.agents.interpreter import InterpretJob, interpret
from swing.agents.runners import Usage
from swing.agents.safety import ContentSafety, endpoint_from_project
from swing.explain.director import direct
from swing.explain.match import load
from swing.gen import generate_match
from swing.gen.cli import write_one


class FakeClient:
    """Content Safety that flags any line containing `word`."""

    def __init__(self, word: str) -> None:
        self.word = word

    async def analyze_text(self, options: Any) -> Any:
        severity = 4 if self.word in options["text"] else 0
        return SimpleNamespace(categories_analysis=[SimpleNamespace(category="Violence", severity=severity)])

    async def close(self) -> None:
        return None


def _safety(word: str) -> ContentSafety:
    s = ContentSafety(credential=None, endpoint="")
    s._client, s._broken = FakeClient(word), False
    return s


class Drafts:
    """A stand-in model that gives these answers in turn, with Content Safety attached."""

    name = "scripted"

    def __init__(self, answers: list[dict[str, str]], safety: ContentSafety) -> None:
        self.answers = answers
        self.safety = safety
        self.usage = Usage()
        self.prompts: list[str] = []

    async def run(self, role: Any, prompt: str, tools: Any, job: Any) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.answers[min(len(self.prompts), len(self.answers)) - 1])


def _card(tmp: Path) -> dict[str, Any]:
    m = generate_match("ash", "brk", 31)
    md = load(write_one(tmp, m.match_id, m.home, m.away, 31, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes))
    return next(c for c in direct(explain_match(md, "offline")["cards"]) if c["cause"]["kind"] == "play_change")


def test_endpoint_comes_from_the_foundry_account() -> None:
    url = "https://matchlens-foundry-812.services.ai.azure.com/api/projects/matchlens"
    assert endpoint_from_project(url) == "https://matchlens-foundry-812.cognitiveservices.azure.com/"


def test_a_flagged_line_goes_back_with_the_problem_then_passes(tmp_path: Path) -> None:
    card = _card(tmp_path)
    good = dict(card["text"])
    bad = good | {"neutral": good["neutral"] + " Brutal."}
    runner = Drafts([bad, good], _safety("Brutal"))
    text, fallback = asyncio.run(interpret(runner, InterpretJob(card["facts"], set())))
    assert text == {k: v.strip() for k, v in good.items()} and not fallback
    assert "Content Safety flagged the neutral line" in runner.prompts[1]
    assert runner.safety.count.flagged == 1 and runner.safety.count.categories == {"Violence": 1}


def test_flagged_twice_falls_back_to_the_rules(tmp_path: Path) -> None:
    card = _card(tmp_path)
    bad = dict(card["text"]) | {"neutral": "Brutal."}
    runner = Drafts([bad], _safety("Brutal"))
    text, fallback = asyncio.run(interpret(runner, InterpretJob(card["facts"], set())))
    assert fallback and "Brutal" not in text["neutral"]


def test_unreachable_service_never_stops_the_lines(tmp_path: Path) -> None:
    card = _card(tmp_path)
    runner = Drafts([dict(card["text"])], ContentSafety(credential=None, endpoint=""))
    _, fallback = asyncio.run(interpret(runner, InterpretJob(card["facts"], set())))
    assert not fallback and runner.safety.count.unscreened == 3
