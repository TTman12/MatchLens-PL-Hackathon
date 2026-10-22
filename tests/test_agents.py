import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from swing.agents.board import Board
from swing.agents.crew import Job, explain_match, explain_match_async, offline_answer, parse
from swing.agents.roles import EXPLAINER, Role
from swing.agents.runners import RunnerError, ToolSpec, Usage
from swing.agents.verifier import Verifier, cause_menu
from swing.broadcast.bundle import build
from swing.explain import explainer
from swing.explain.match import load
from swing.explain.watcher import watch
from swing.gen import generate_match
from swing.gen.cli import write_one


def _write(tmp: Path, home: str, away: str, seed: int) -> Path:
    m = generate_match(home, away, seed)
    return write_one(tmp, m.match_id, m.home, m.away, seed, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes)


def _key(c: dict[str, Any]) -> tuple[Any, ...]:
    return (c["at"], c["cause"]["kind"], c["cause"].get("team"), [(s["label"], s["team"], s["after"]) for s in c["stats"]])


class Scripted:
    """A stand-in model: specialists call their tool; the Explainer answers from `explainer`."""

    name = "scripted"

    def __init__(self, explainer: Any, fail: tuple[str, ...] = ()) -> None:
        self.usage = Usage()
        self.explainer = explainer
        self.fail = fail

    async def run(self, role: Role, prompt: str, tools: list[ToolSpec], job: Job) -> str:
        if role.key in self.fail:
            raise RunnerError("timed out")
        if role is EXPLAINER:
            return str(self.explainer(job, tools))
        return "Sure.\n```json\n" + offline_answer(role, tools, job) + "\n```"

    async def close(self) -> None:
        return None


def test_offline_crew_matches_the_deterministic_explainer(tmp_path: Path) -> None:
    for seed, (h, a) in enumerate([("ash", "brk"), ("cal", "dun")]):
        md = load(_write(tmp_path, h, a, 40 + seed))
        crew = explain_match(md, "offline")
        assert [_key(c) for c in crew["cards"]] == [_key(c) for c in explainer.explain_match(md)["cards"]]
        assert not any(c["agents"]["fallback"] for c in crew["cards"])


def test_parse_takes_the_last_answer() -> None:
    text = 'Checked: {"ok": false} then\n```json\n{"cause": "C1", "stats": []}\n```\n{"cause": "C2", "stats": ["F1"]}'
    assert parse(text, ("cause",)) == {"cause": "C2", "stats": ["F1"]}
    with pytest.raises(ValueError):
        parse("no idea", ("cause",))


def test_rejected_draft_goes_back_once_then_falls_back(tmp_path: Path) -> None:
    md = load(_write(tmp_path, "brk", "cal", 7))
    calls: list[int] = []

    def stubborn(job: Job, tools: list[ToolSpec]) -> str:
        calls.append(job.m.now)
        return json.dumps({"cause": "C99", "stats": []})

    result = asyncio.run(explain_match_async(md, Scripted(stubborn)))
    det = explainer.explain_match(md)["cards"]
    for card, ref in zip(result["cards"], det, strict=True):
        assert card["agents"]["fallback"]
        rounds = [t for t in card["agents"]["trace"] if t["agent"] == "verifier"]
        assert [r["status"] for r in rounds] == ["rejected", "rejected"]
        assert _key(card) == _key(ref)  # the fallback is the deterministic card
    assert len(calls) == 2 * len(det)


def test_fixed_draft_passes_on_the_second_round(tmp_path: Path) -> None:
    md = load(_write(tmp_path, "ash", "cal", 9))
    seen: set[int] = set()

    def learns(job: Job, tools: list[ToolSpec]) -> str:
        if id(job) not in seen:
            seen.add(id(job))
            return json.dumps({"cause": "C1", "stats": ["F9999"]})
        return offline_answer(EXPLAINER, tools, job)

    cards = asyncio.run(explain_match_async(md, Scripted(learns)))["cards"]
    assert cards and not any(c["agents"]["fallback"] for c in cards)
    for c in cards:
        rounds = [t["status"] for t in c["agents"]["trace"] if t["agent"] == "verifier"]
        assert rounds == ["rejected", "passed"]


def test_a_failed_specialist_lowers_confidence(tmp_path: Path) -> None:
    md = load(_write(tmp_path, "dun", "ash", 12))
    full = asyncio.run(explain_match_async(md, Scripted(lambda job, tools: offline_answer(EXPLAINER, tools, job))))
    part = asyncio.run(
        explain_match_async(md, Scripted(lambda job, tools: offline_answer(EXPLAINER, tools, job), fail=("players",)))
    )
    for a, b in zip(full["cards"], part["cards"], strict=True):
        assert b["agents"]["missing"] == ["players"]
        assert b["cause"]["confidence"] < a["cause"]["confidence"]
        assert not any(f["agent"] == "players" for f in b["findings"]["players"])


def test_verifier_recomputes_numbers(tmp_path: Path) -> None:
    from swing.explain.specialists import investigate

    md = load(_write(tmp_path, "cal", "brk", 5))
    for m in (m for m in watch(md) if m.shifted):  # the first shift with a strong team-play finding
        part = md.until(m.now)
        board = Board()
        for agent, found in investigate(part, m).items():
            board.post(agent, [dict(f) for f in found])
        strong = [
            k
            for k, f in board.findings.items()
            if f["agent"] == "team_play" and abs(f["effect_sd"]) >= 1.5 and f["metric"] != "field_tilt"
        ]
        if strong:
            break
    fid = strong[0]
    menu = cause_menu(part, m, board.by_agent())
    v = Verifier(part, m, board, menu)
    play = next(o["id"] for o in menu if o["kind"] in ("play_change", "recovery", "goal_lift", "chasing_the_game"))
    assert not [p for p in v.check(play, [fid]) if "match the tables" in p]
    board.findings[fid]["after"] += 3  # a number that no longer matches the tables
    assert any("match the tables" in p for p in v.check(play, [fid]))
    assert v.check("C42", [])[0].startswith("C42 is not on the cause menu")


def test_bundle_carries_the_agents_log(tmp_path: Path) -> None:
    md = load(_write(tmp_path, "ash", "brk", 21))
    b = build(md, explain_match(md, "offline"))
    assert b["agents"]["runner"] == "offline"
    hoods = [c["hood"] for c in b["cards"]]
    assert hoods and all(h and len(h["specialists"]) == 4 and h["verifier"] for h in hoods)
    assert all(c["hood"] is None for c in build(md)["cards"])
