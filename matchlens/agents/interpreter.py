"""The Interpreter: from a verified card's numbers to what they mean, for each fan.

The Explainer and the Verifier settle what the card shows. The Interpreter (a Foundry agent) then
reads those facts and writes one line for a neutral and one for each club's fans, inferring what is
going on rather than reading the stats out. A check in code holds it to the facts: no numbers, only
the two clubs and the card's players, nothing the data can't see, and score talk that matches the
score. A rejected draft goes back once with the problems listed; after that, or if the model fails,
the card keeps the deterministic lines from matchlens/explain/insight.py.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..explain.insight import lines
from ..explain.match import MatchData
from ..telemetry import span
from .crew import parse
from .roles import INTERPRETER
from .runners import Runner, RunnerError
from .safety import screen

MAX_WORDS = 24
UNSEEN = re.compile(
    r"\b(manager|coach|boss|gaffer|instruct\w*|told|orders|injur\w*|referee|ref|VAR|crowd|weather|rain|"
    r"dressing room|formation|tactic\w*|team talk)\b",
    re.I,
)
TIRED = re.compile(r"\b(tir\w+|fatigue\w*|legs|exhaust\w*|leggy|fresh)\b", re.I)
TEN_MEN = re.compile(r"\b(ten|10) men\b|\bred card\b|\bdown to ten\b|\bextra man\b", re.I)
EQUALISER = re.compile(r"\bequalis\w*|\bleveller\b", re.I)
LEAD = re.compile(r"\b(lead|ahead|in front)\b", re.I)


@dataclass
class InterpretJob:
    """One card being interpreted. `facts` is the card's facts block (matchlens/explain/insight.py)."""

    facts: dict[str, Any]
    others: set[str]  # names of players in the match who are not on the card
    trace: list[dict[str, Any]] = field(default_factory=list)


def check_lines(job: InterpretJob, draft: dict[str, Any]) -> list[str]:
    """What is wrong with a draft, if anything. The lines must stay inside the facts."""
    fx = job.facts
    teams = fx["teams"]
    keys = ["neutral", *teams]
    problems = [f"missing the line for {k}" for k in keys if not str(draft.get(k) or "").strip()]
    if problems:
        return problems
    cause = fx["cause"]
    on_card = {s["player"] for s in fx["stats"] if s.get("player")} | {s["replaced"] for s in fx["stats"] if s.get("replaced")}
    states = {t["state"] for t in teams.values()}
    gaps = [abs(a["goals"] - b["goals"]) for a in teams.values() for b in teams.values()]
    for k in keys:
        line = str(draft[k]).strip()
        who = "the neutral line" if k == "neutral" else f"the {teams[k]['name']} line"
        words = len(line.split())
        if words > MAX_WORDS:
            problems.append(f"{who} has {words} words; keep it to {MAX_WORDS}")
        if re.search(r"\d", line):
            problems.append(f"{who} has a number in it; the card shows the numbers")
        if m := UNSEEN.search(line):
            problems.append(f"{who} says '{m.group(0)}', which the data can't see")
        if TIRED.search(line) and cause not in ("fatigue", "substitution_impact", "sub_no_change"):
            problems.append(f"{who} talks about tiredness, but this is not a fatigue or substitution card")
        if TEN_MEN.search(line) and not cause.startswith("red_card"):
            problems.append(f"{who} mentions a red card or ten men, but there isn't one")
        if EQUALISER.search(line) and max(gaps) != 1:
            problems.append(f"{who} talks about an equaliser, but no one is exactly one goal behind")
        if LEAD.search(line) and "leading" not in states:
            problems.append(f"{who} talks about a lead, but the scores are level")
        for name in job.others:
            if re.search(rf"\b{re.escape(name)}\b", line) and name not in on_card:
                problems.append(f"{who} names {name}, who is not on the card")
        named = [t["name"] for t in teams.values()] + sorted(on_card)
        if not any(n in line for n in named):
            problems.append(f"{who} names neither club nor a player on the card")
    if len({str(draft[k]).strip() for k in keys}) < len(keys):
        problems.append("the lines are identical; write each for its viewer")
    return problems


def interpreter_prompt(job: InterpretJob, rejected: tuple[dict[str, Any], list[str]] | None = None) -> str:
    fx = job.facts
    home, away = list(fx["teams"])
    parts = [
        f"Home club id: {home} ({fx['teams'][home]['name']}). Away club id: {away} ({fx['teams'][away]['name']}).",
        "Facts:\n" + json.dumps(fx, indent=1),
        "Draft lines from the rules (improve on them):\n" + json.dumps(lines(fx), indent=1),
    ]
    if rejected:
        draft, problems = rejected
        parts.append(f"Your draft {json.dumps(draft)} was rejected:\n- " + "\n- ".join(problems) + "\nFix it.")
    return "\n\n".join(parts)


def offline_lines(job: InterpretJob) -> str:
    return json.dumps(lines(job.facts))


async def interpret(runner: Runner, job: InterpretJob) -> tuple[dict[str, str], bool]:
    """(the lines, whether they fell back to the rules)."""
    rejected: tuple[dict[str, Any], list[str]] | None = None
    keys = ("neutral", *job.facts["teams"])
    for round_ in (1, 2):
        t0 = time.monotonic()
        try:
            draft = parse(await runner.run(INTERPRETER, interpreter_prompt(job, rejected), [], job), ("neutral",))
        except (RunnerError, ValueError, TypeError) as exc:
            job.trace.append({"round": round_, "status": "failed", "error": str(exc)[:200], "ms": _ms(t0)})
            break
        problems = check_lines(job, draft) or await screen(runner, {k: str(draft[k]) for k in keys})
        job.trace.append({"round": round_, "status": "rejected" if problems else "passed", "problems": problems, "ms": _ms(t0)})
        if not problems:
            return {k: str(draft[k]).strip() for k in keys}, False
        rejected = ({k: draft.get(k) for k in keys}, problems)
    return lines(job.facts), True


def _ms(t0: float) -> int:
    return round(1000 * (time.monotonic() - t0))


async def interpret_cards(runner: Runner, md: MatchData, cards: list[dict[str, Any]]) -> None:
    """Rewrite each card's text with the Interpreter, in place, and log what it did on the card."""
    names = set(md.names.values())

    async def one(card: dict[str, Any]) -> None:
        on_card = {s.get("name") for s in card["stats"]} | {s.get("vs") for s in card["stats"]}
        job = InterpretJob(card["facts"], {n for n in names if n not in on_card})
        card["text"], fallback = await interpret(runner, job)
        card.setdefault("agents", {})["interpreter"] = {"fallback": fallback, "rounds": job.trace}

    with span("interpreter", cards=len(cards)):
        await asyncio.gather(*(one(c) for c in cards))
