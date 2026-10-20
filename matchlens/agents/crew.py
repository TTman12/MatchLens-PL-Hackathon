"""The crew: the Watcher's moments explained by agents.

For each moment the Watcher raises:

1. Four specialists run at once (team play, players, substitutions, match events). Each calls its
   tool, which computes findings from the match tables and posts them to the shared board, then
   says which of its findings matter, or "not me".
2. The Explainer reads the board and a menu of causes the evidence allows, chooses a cause and the
   one or two findings to show, and checks its draft with the Verifier as a tool.
3. The Verifier rechecks the final draft. A rejected draft goes back once with the problems
   listed; a second rejection, or any agent failing, falls back to the deterministic Explainer.

A specialist that fails leaves its findings off the board; the Explainer works with what is
there and the card's confidence drops. Every step is logged on the card under "agents".

    matchlens-agents out/matches/ash-brk-7 --runner foundry
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..explain.explainer import assemble, decide_cause, fallback_stats, pick_stats
from ..explain.match import MatchData, load
from ..explain.specialists import SPECIALISTS, Finding
from ..explain.watcher import Moment, momentum_series, watch
from .board import Board, is_stat
from .roles import EXPLAINER, SPECIALIST_ROLES, Role
from .runners import Runner, RunnerError, ToolSpec, make_runner
from .verifier import Option, Verifier, cause_menu

TOOL_VIEW = 12  # findings a specialist's tool hands back to its agent
MISSING_PENALTY = 0.1  # confidence lost per specialist that didn't report


@dataclass
class Job:
    """One moment being worked on: the match as it stood, and the shared board."""

    md: MatchData
    m: Moment
    clock: str
    board: Board = field(default_factory=Board)
    menu: list[Option] = field(default_factory=list)
    verifier: Verifier | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    checks: int = 0

    def log(self, agent: str, status: str, t0: float, **extra: Any) -> None:
        self.trace.append({"agent": agent, "status": status, "ms": round(1000 * (time.monotonic() - t0)), **extra})


def describe(job: Job) -> str:
    md, m = job.md, job.m
    home, away = md.teams
    score = md.score_at(m.now)
    lines = [
        f"Match: {md.short(home)} (home, team id {home}) v {md.short(away)} (away, team id {away}).",
        f"Moment at {job.clock}, using play up to then. Mode: {m.mode}. Anchor: {md.clock_of(m.anchor_m)}.",
        f"Score now: {score[home]}-{score[away]}.",
        f"Momentum (home share of final-third play): {m.momentum_before:.0f}% before the anchor, {m.momentum_now:.0f}% since.",
        f"Team that gained: {m.gainer or 'neither (momentum did not move)'}; swing {m.swing:.0f} points.",
    ]
    for e in m.events:
        who = md.names.get(e.player_id or "", "")
        off = md.names.get(e.player_off_id or "", "")
        lines.append(f"Event: {e.kind} {e.team_id} {e.clock} {who}{' for ' + off if off else ''}".rstrip())
    return "\n".join(lines)


def specialist_tool(job: Job, key: str) -> ToolSpec:
    def investigate() -> str:
        ids = [k for k, f in job.board.findings.items() if f["agent"] == key]
        if not ids:
            ids = job.board.post(key, SPECIALISTS[key](job.md, job.m))
        stats = sorted((k for k in ids if is_stat(job.board.findings[k])), key=lambda k: -abs(job.board.findings[k]["effect_sd"]))
        shown = stats[:TOOL_VIEW] + [k for k in ids if not is_stat(job.board.findings[k])]
        return json.dumps({"posted": len(ids), "findings": job.board.view(shown)})

    return ToolSpec(
        f"investigate_{key}",
        f"Compute the {key.replace('_', ' ')} findings for this moment and post them to the board.",
        investigate,
    )


def check_tool(job: Job) -> ToolSpec:
    def check_card(cause: str, stats: list[str]) -> str:
        """Recompute the numbers in a draft card and check it against the screen rules."""
        assert job.verifier is not None
        job.checks += 1
        problems = job.verifier.check(cause, list(stats))
        return json.dumps({"ok": not problems, "problems": problems})

    return ToolSpec("check_card", "Recompute a draft card's numbers and check it against the screen rules.", check_card)


def parse(text: str, keys: tuple[str, ...]) -> dict[str, Any]:
    """The last JSON object in a model's reply that has one of `keys`, tolerating code fences,
    stray prose and earlier drafts or echoed tool results in the same reply."""
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    i = text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict) and any(k in obj for k in keys):
            found.append(obj)
        i = text.find("{", end)
    if not found:
        raise ValueError("no answer object in the reply")
    return found[-1]


async def run_specialist(runner: Runner, role: Role, job: Job) -> bool:
    t0 = time.monotonic()
    tool = specialist_tool(job, role.key)
    try:
        answer = parse(await runner.run(role, describe(job), [tool], job), ("verdict", "highlights"))
    except (RunnerError, ValueError) as exc:
        job.log(role.key, "failed", t0, error=str(exc)[:200])
        return False
    called = any(f["agent"] == role.key for f in job.board.findings.values())
    if not called:  # the model answered without looking: its findings still go up, its verdict doesn't count
        tool.fn()
    verdict = str(answer.get("verdict")) if answer.get("verdict") in ("relevant", "not_me") else "relevant"
    highlights = [h for h in answer.get("highlights") or [] if isinstance(h, str)][:3]
    job.board.note(role.key, verdict if called else "unread", highlights if called else [], str(answer.get("note") or ""))
    job.log(
        role.key,
        "ok" if called else "no_tool_call",
        t0,
        verdict=verdict,
        highlights=highlights,
        note=str(answer.get("note") or "")[:120],
    )
    return True


def explainer_prompt(job: Job, rejected: tuple[dict[str, Any], list[str]] | None = None) -> str:
    md = job.md
    menu = [
        {k: v for k, v in o.items() if k in ("id", "kind", "team", "name", "meaning")}
        | ({"team": md.short(o["team"])} if o.get("team") else {})
        for o in job.menu
    ]
    parts = [
        describe(job),
        "Cause menu:\n" + "\n".join(json.dumps(o) for o in menu),
        "Specialists' verdicts:\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in job.board.notes.items()),
        "Findings board (stats that could go on screen, largest effect first, then match context):\n"
        + "\n".join(json.dumps(r) for r in job.board.view()),
    ]
    if rejected:
        draft, problems = rejected
        parts.append(f"Your draft {json.dumps(draft)} was rejected by the Verifier:\n- " + "\n- ".join(problems) + "\nFix it.")
    return "\n\n".join(parts)


async def run_explainer(runner: Runner, job: Job) -> tuple[Option, list[Finding], str] | None:
    """The verified (cause, stats, why), or None if the Explainer couldn't produce one."""
    assert job.verifier is not None
    rejected: tuple[dict[str, Any], list[str]] | None = None
    for round_ in (1, 2):
        t0 = time.monotonic()
        try:
            draft = parse(await runner.run(EXPLAINER, explainer_prompt(job, rejected), [check_tool(job)], job), ("cause",))
            cause_id = str(draft.get("cause"))
            stat_ids = [str(s) for s in draft.get("stats") or []]
        except (RunnerError, ValueError, TypeError) as exc:
            job.log("explainer", "failed", t0, error=str(exc)[:200], round=round_)
            return None
        problems = job.verifier.check(cause_id, stat_ids)
        job.log("explainer", "ok", t0, round=round_, cause=cause_id, stats=stat_ids, why=str(draft.get("why") or "")[:160])
        job.trace.append(
            {"agent": "verifier", "status": "rejected" if problems else "passed", "problems": problems, "round": round_}
        )
        if not problems:
            cause = next(o for o in job.menu if o["id"] == cause_id)
            return cause, [job.board.findings[s] for s in stat_ids], str(draft.get("why") or "")
        rejected = (draft, problems)
    return None


def _cause(o: Option) -> dict[str, Any]:
    return {k: v for k, v in o.items() if k not in ("id", "meaning", "name")}


async def explain_moment(runner: Runner, md_full: MatchData, m: Moment) -> dict[str, Any]:
    job = Job(md_full.until(m.now), m, md_full.clock_of(m.now - 1))
    reported = await asyncio.gather(*(run_specialist(runner, r, job) for r in SPECIALIST_ROLES))
    found = job.board.by_agent()
    job.menu = cause_menu(job.md, m, found)
    job.verifier = Verifier(job.md, m, job.board, job.menu)
    result = await run_explainer(runner, job)
    fallback = result is None
    if result is None:
        cause_d, lead = decide_cause(job.md, m, found)
        stats = pick_stats(m, found, lead)
        why = "deterministic fallback"
    else:
        option, stats, why = result
        cause_d = _cause(option)
    if not stats:
        stats = fallback_stats(m, found)
    penalty = MISSING_PENALTY * reported.count(False) + (0.05 if fallback else 0.0)
    card = assemble(job.md, m, job.clock, found, cause_d, stats, penalty)
    card["agents"] = {
        "runner": runner.name,
        "fallback": fallback,
        "why": why,
        "board": len(job.board.findings),
        "checks": job.checks,
        "missing": [r.key for r, ok in zip(SPECIALIST_ROLES, reported, strict=True) if not ok],
        "trace": job.trace,
    }
    return card


def offline_answer(role: Role, tools: list[ToolSpec], job: Job) -> str:
    """What the deterministic rules would answer, in the agents' reply format."""
    if role is not EXPLAINER:
        payload = json.loads(tools[0].fn())
        stats = [f for f in payload["findings"] if "effect_sd" in f and abs(f["effect_sd"]) >= 2]
        events = [f["id"] for f in payload["findings"] if f["claim_type"] in ("goal", "red_card")]
        highlights = [f["id"] for f in stats[:3]] or events[:3]
        return json.dumps({"verdict": "relevant" if highlights else "not_me", "highlights": highlights, "note": ""})
    found = job.board.by_agent()
    cause, lead = decide_cause(job.md, job.m, found)
    stats = pick_stats(job.m, found, lead)
    option = next(
        (
            o
            for o in job.menu
            if o["kind"] == cause["kind"] and o.get("team") == cause.get("team") and o.get("player") == cause.get("player")
        ),
        job.menu[0],
    )
    return json.dumps({"cause": option["id"], "stats": [job.board.id_of(f) for f in stats], "why": "deterministic rules"})


async def explain_match_async(md: MatchData, runner: Runner) -> dict[str, Any]:
    cards = await asyncio.gather(*(explain_moment(runner, md, m) for m in watch(md)))
    return {
        "match_id": md.meta["match_id"],
        "teams": [{"team_id": t["team_id"], "name": t["name"], "short_name": t.get("short_name")} for t in md.meta["teams"]],
        "momentum": momentum_series(md),
        "timeline": [
            {"kind": k.kind, "m": k.m, "clock": k.clock, "team": k.team_id, "name": md.names.get(k.player_id or "", "")}
            for k in md.key_events
        ],
        "cards": list(cards),
        "agents": {
            "runner": runner.name,
            "usage": runner.usage.as_dict(),
            "versions": dict(getattr(runner, "versions", {})),
        },
    }


def explain_match(md: MatchData, runner: str | Runner = "offline") -> dict[str, Any]:
    """Every card for a match, explained by the agent crew. Same shape as explain.explain_match."""

    async def go() -> dict[str, Any]:
        r = make_runner(runner) if isinstance(runner, str) else runner
        try:
            return await explain_match_async(md, r)
        finally:
            if isinstance(runner, str):
                await r.close()

    return asyncio.run(go())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--runner", default="offline", choices=["offline", "foundry"])
    ap.add_argument("--json", type=Path, help="write every card, with the agents' log, to this file")
    args = ap.parse_args()
    md = load(args.folder)
    result = explain_match(md, args.runner)
    if args.json:
        args.json.write_text(json.dumps(result, indent=1) + "\n")
    for c in result["cards"]:
        a = c["agents"]
        stats = "; ".join(
            f"{md.short(s['team']) if not s.get('name') else s['name']} {s['label']} {s['after']:g} (was {s['before']:g})"
            for s in c["stats"]
        )
        flag = " FALLBACK" if a["fallback"] else ""
        print(f"{c['clock']:>7} {c['anchor']['label']:<32} {c['cause']['kind']:<20} {stats}{flag}")
        if a["why"] and not a["fallback"]:
            print(f"{'':>8}why: {a['why']}")
    print(json.dumps(result["agents"]))


if __name__ == "__main__":
    main()
