"""The Recapper: the full-time headline for each fan, written from the recap's facts.

The recap's graphics (matchlens/explain/recap.py) are fixed by code: the score, the quarter-hour
spells, the turning points, the stats and the standouts. The Recapper (a Foundry agent) writes the
one line above them, for a neutral and for each club's fans. A check in code holds it to the
facts: no numbers, only the two clubs, no win in a draw or draw in a win, a late goal, comeback or
red card only when there was one, nothing the data can't see. A rejected draft goes back once with
the problems listed; after that, or if the model fails, the recap keeps the rules' headlines.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..explain.recap import LATE, _minute
from .crew import parse
from .interpreter import TEN_MEN, UNSEEN
from .roles import RECAPPER
from .runners import Runner, RunnerError
from .safety import screen

MAX_WORDS = 20
WIN = re.compile(r"\b(beat|beats|beaten|won|wins|victory|defeat\w*|winners?|lost|loses|losing)\b", re.I)
DRAW = re.compile(r"\b(draw|drew|drawn|stalemate|a point|the points|level at|all square)\b", re.I)
LATE_WORDS = re.compile(r"\b(late|last[- ]gasp|stoppage time|injury time|dying)\b", re.I)
COMEBACK = re.compile(r"\b(came from behind|come(-| )?back|fight(-| )?back|turned it around|from behind)\b", re.I)


@dataclass
class RecapJob:
    """One match's headlines. `facts` is the recap's facts block; `rules` the rules' headlines."""

    facts: dict[str, Any]
    rules: dict[str, str]
    others: set[str]  # player names: the headline names clubs only
    trace: list[dict[str, Any]] = field(default_factory=list)


def check_recap(job: RecapJob, draft: dict[str, Any]) -> list[str]:
    fx = job.facts
    teams = fx["teams"]
    keys = ["neutral", *teams]
    problems = [f"missing the line for {k}" for k in keys if not str(draft.get(k) or "").strip()]
    if problems:
        return problems
    draw = fx["result"] == "draw"
    late = any(_minute(g["clock"]) >= LATE for g in fx["goals"])
    names = [t["name"] for t in teams.values()]
    for k in keys:
        line = str(draft[k]).strip()
        who = "the neutral line" if k == "neutral" else f"the {teams[k]['name']} line"
        if (n := len(line.split())) > MAX_WORDS:
            problems.append(f"{who} has {n} words; keep it to {MAX_WORDS}")
        if re.search(r"\d", line):
            problems.append(f"{who} has a number in it; the graphics show the numbers")
        if m := UNSEEN.search(line):
            problems.append(f"{who} says '{m.group(0)}', which the data can't see")
        if draw and (m := WIN.search(line)):
            problems.append(f"{who} says '{m.group(0)}', but the match was a draw")
        if not draw and (m := DRAW.search(line)):
            problems.append(f"{who} says '{m.group(0)}', but the match had a winner")
        if (m := LATE_WORDS.search(line)) and not late:
            problems.append(f"{who} says '{m.group(0)}', but there was no goal after {LATE}'")
        if (m := COMEBACK.search(line)) and fx["pattern"] != "comeback":
            problems.append(f"{who} says '{m.group(0)}', but the winner never trailed")
        if TEN_MEN.search(line) and not fx["red_cards"]:
            problems.append(f"{who} mentions a red card or ten men, but there wasn't one")
        if not any(n in line for n in names):
            problems.append(f"{who} names neither club")
        for name in job.others:
            if re.search(rf"\b{re.escape(name)}\b", line) and name not in names:
                problems.append(f"{who} names {name}; name the clubs only")
    if len({str(draft[k]).strip() for k in keys}) < len(keys):
        problems.append("the lines are identical; write each for its viewer")
    return problems


def recap_prompt(job: RecapJob, rejected: tuple[dict[str, Any], list[str]] | None = None) -> str:
    home, away = list(job.facts["teams"])
    parts = [
        f"Home club id: {home} ({job.facts['teams'][home]['name']}). Away club id: {away} ({job.facts['teams'][away]['name']}).",
        "Facts:\n" + json.dumps(job.facts, indent=1),
        "Draft from the rules (improve on it):\n" + json.dumps(job.rules, indent=1),
    ]
    if rejected:
        draft, problems = rejected
        parts.append(f"Your draft {json.dumps(draft)} was rejected:\n- " + "\n- ".join(problems) + "\nFix it.")
    return "\n\n".join(parts)


def offline_recap(job: RecapJob) -> str:
    return json.dumps(job.rules)


async def write_recap(runner: Runner, job: RecapJob) -> tuple[dict[str, str], bool]:
    """(the headlines, whether they fell back to the rules)."""
    rejected: tuple[dict[str, Any], list[str]] | None = None
    keys = ("neutral", *job.facts["teams"])
    for round_ in (1, 2):
        t0 = time.monotonic()
        try:
            draft = parse(await runner.run(RECAPPER, recap_prompt(job, rejected), [], job), ("neutral",))
        except (RunnerError, ValueError, TypeError) as exc:
            job.trace.append({"round": round_, "status": "failed", "error": str(exc)[:200], "ms": _ms(t0)})
            break
        problems = check_recap(job, draft) or await screen(runner, {k: str(draft[k]) for k in keys})
        job.trace.append({"round": round_, "status": "rejected" if problems else "passed", "problems": problems, "ms": _ms(t0)})
        if not problems:
            return {k: str(draft[k]).strip() for k in keys}, False
        rejected = ({k: draft.get(k) for k in keys}, problems)
    return dict(job.rules), True


def _ms(t0: float) -> int:
    return round(1000 * (time.monotonic() - t0))


async def recap_bundle(runner: Runner, b: dict[str, Any]) -> None:
    """Rewrite a bundle's recap headlines with the Recapper, in place, and log what it did."""
    r = b["recap"]
    names = {p["name"] for p in b["stats"]["players"]}
    job = RecapJob(r["facts"], dict(r["text"]), names)
    r["text"], fallback = await write_recap(runner, job)
    r["agents"] = {"runner": runner.name, "fallback": fallback, "rounds": job.trace}
