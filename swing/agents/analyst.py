"""The Analyst: what a club could do about the momentum, for each fan, from stat-backed options.

After the Interpreter has said what a card means, the Analyst (a Foundry agent) gives the take fans
debate: how the side that lost momentum could win it back, or what the side that has it should keep
doing. It may only pick from a menu of levers that a stat in the match backs
(swing/explain/analysis.py), and a check in code holds its lines to the pick: the right club,
the pick's idea, no other tactical change the stats didn't back, no numbers, nothing the data can't
see. A rejected draft goes back once with the problems listed; after that, or if the model fails,
the card keeps the deterministic lines.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..explain.analysis import BY_KEY, EXCLUSIVE, default_picks, lenses, lines, speaks_to
from ..explain.match import MatchData
from ..telemetry import span
from .crew import parse
from .interpreter import EQUALISER, LEAD, TEN_MEN, TIRED
from .roles import ANALYST
from .runners import Runner, RunnerError
from .safety import screen

MAX_WORDS = 26
UNSEEN = re.compile(
    r"\b(manager|coach|boss|gaffer|instruct\w*|told|orders|injur\w*|referee|ref|VAR|crowd|weather|rain|"
    r"dressing room|formation|team talk|back (three|four|five)|bring (on|off)|sub(stitut\w*)?|hooked)\b",
    re.I,
)


@dataclass
class AnalystJob:
    """One card being analysed. `facts` is the card's analysis facts block."""

    facts: dict[str, Any]
    cause: str  # the card's cause, for the red-card and tiredness checks
    others: set[str]  # names of every player in the match: the analysis names clubs only
    trace: list[dict[str, Any]] = field(default_factory=list)


def check_analysis(job: AnalystJob, draft: dict[str, Any]) -> list[str]:
    """What is wrong with a draft, if anything. Each line must argue its club's picked option."""
    fx = job.facts
    teams = fx["teams"]
    by_id = {o["id"]: o for o in fx["options"]}
    raw = draft.get("picks")
    picks: dict[str, str] = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    problems = []
    for team in {o["team"] for o in fx["options"]}:
        pick = picks.get(team)
        if pick not in by_id:
            problems.append(f"no valid pick for {team}: choose one of its option ids")
        elif by_id[pick]["team"] != team:
            problems.append(f"{pick} is an option for {by_id[pick]['team']}, not {team}")
    for team in picks:
        if team not in {o["team"] for o in fx["options"]}:
            problems.append(f"{team} has no options; leave it out")
    if problems:
        return problems
    states = {t["state"] for t in teams.values()}
    gaps = [abs(a["goals"] - b["goals"]) for a in teams.values() for b in teams.values()]
    for lens, team in lenses(fx, picks).items():
        line = str(draft.get(lens) or "").strip()
        who = "the neutral line" if lens == "neutral" else f"the {teams[lens]['name']} line"
        if not line:
            problems.append(f"missing {who}")
            continue
        lever = BY_KEY[by_id[picks[team]]["lever"]]
        if (n := len(line.split())) > MAX_WORDS:
            problems.append(f"{who} has {n} words; keep it to {MAX_WORDS}")
        if re.search(r"\d", line):
            problems.append(f"{who} has a number in it; the card shows the stat")
        if m := UNSEEN.search(line):
            problems.append(f"{who} says '{m.group(0)}', which the data can't see")
        if teams[team]["name"] not in line:
            problems.append(f"{who} should be about {teams[team]['name']}, by name")
        if not any(speaks_to(line, topic) for topic in lever.topics):
            problems.append(f"{who} doesn't argue the option picked ({lever.idea})")
        for topic in EXCLUSIVE:
            if topic not in lever.topics and speaks_to(line, topic):
                problems.append(f"{who} suggests a change of '{topic}' that its option's stat doesn't back")
        for name in job.others:
            if re.search(rf"\b{re.escape(name)}\b", line):
                problems.append(f"{who} names {name}; name the clubs only")
        if TIRED.search(line):
            problems.append(f"{who} talks about tiredness, which no option is about")
        if TEN_MEN.search(line) and not job.cause.startswith("red_card"):
            problems.append(f"{who} mentions a red card or ten men, but there isn't one")
        if EQUALISER.search(line) and max(gaps) != 1:
            problems.append(f"{who} talks about an equaliser, but no one is exactly one goal behind")
        if LEAD.search(line) and "leading" not in states:
            problems.append(f"{who} talks about a lead, but the scores are level")
    return problems


def analyst_prompt(job: AnalystJob, rejected: tuple[dict[str, Any], list[str]] | None = None) -> str:
    fx = job.facts
    home, away = list(fx["teams"])
    picks = default_picks(fx)
    parts = [
        f"Home club id: {home} ({fx['teams'][home]['name']}). Away club id: {away} ({fx['teams'][away]['name']}).",
        "Facts:\n" + json.dumps(fx, indent=1),
        "Draft from the rules (improve on it):\n" + json.dumps({"picks": picks, **lines(fx, picks)}, indent=1),
    ]
    if rejected:
        draft, problems = rejected
        parts.append(f"Your draft {json.dumps(draft)} was rejected:\n- " + "\n- ".join(problems) + "\nFix it.")
    return "\n\n".join(parts)


def offline_analysis(job: AnalystJob) -> str:
    picks = default_picks(job.facts)
    return json.dumps({"picks": picks, **lines(job.facts, picks)})


async def analyse(runner: Runner, job: AnalystJob) -> tuple[dict[str, str], dict[str, str], bool]:
    """(the picks, the lines, whether they fell back to the rules)."""
    rejected: tuple[dict[str, Any], list[str]] | None = None
    for round_ in (1, 2):
        t0 = time.monotonic()
        try:
            draft = parse(await runner.run(ANALYST, analyst_prompt(job, rejected), [], job), ("picks",))
        except (RunnerError, ValueError, TypeError) as exc:
            job.trace.append({"round": round_, "status": "failed", "error": str(exc)[:200], "ms": _ms(t0)})
            break
        problems = check_analysis(job, draft)
        if not problems:
            picks = {str(k): str(v) for k, v in draft["picks"].items()}
            problems = await screen(runner, {k: str(draft[k]) for k in lenses(job.facts, picks)})
        job.trace.append({"round": round_, "status": "rejected" if problems else "passed", "problems": problems, "ms": _ms(t0)})
        if not problems:
            picks = {str(k): str(v) for k, v in draft["picks"].items()}
            return picks, {k: str(draft[k]).strip() for k in lenses(job.facts, picks)}, False
        rejected = (draft, problems)
    picks = default_picks(job.facts)
    return picks, lines(job.facts, picks), True


def _ms(t0: float) -> int:
    return round(1000 * (time.monotonic() - t0))


async def analyse_cards(runner: Runner, md: MatchData, cards: list[dict[str, Any]]) -> None:
    """Rewrite each card's analysis with the Analyst, in place, and log what it did on the card."""
    names = set(md.names.values())

    async def one(card: dict[str, Any]) -> None:
        a = card.get("analysis")
        if not a or not a["facts"]["options"]:
            return
        job = AnalystJob(a["facts"], card["cause"]["kind"], names)
        a["picks"], a["text"], fallback = await analyse(runner, job)
        card.setdefault("agents", {})["analyst"] = {"fallback": fallback, "rounds": job.trace}

    with span("analyst", cards=len(cards)):
        await asyncio.gather(*(one(c) for c in cards))
