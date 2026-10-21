"""Score the Watcher and Explainer against the generator's hidden truth.

The agents never see truth; this is the only code that reads it. For each card we ask what really
happened in the window, using the truth's per-minute state (each team's plan, including score
effects, and its flow) and its decision log:

- **real swing**: did the hidden state actually move toward the team the card says gained?
- **plan-driven**: did some plan parameter of either team move by at least PLAN_MOVE?
- **event backed**: for a shift put down to an event, did that event really lead to a decision?
- **cause claims**: red-card reshape, chasing the game and fatigue are checked against the log.

    matchlens-explain-eval --matches 100 --seed 9000

Season seed 2026 was used for tuning; the default evaluation seed is kept apart from it.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from .explainer import explain_match
from .match import MatchData, load
from .watcher import tilt

PLAN_MOVE = 0.25
PARAMS = ("block", "press", "directness", "tempo", "width", "risk", "aggression")
RESHAPES = {"park_the_bus", "drop_deeper"}


def _minutes(truth: dict[str, Any], lo: int, hi: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    mins = {r["m"]: r for r in truth["minutes"]}
    a, b = mins.get(max(lo, 0)), mins.get(min(hi, max(mins)))
    return (a, b) if a and b else None


def plan_moves(truth: dict[str, Any], lo: int, hi: int) -> dict[str, dict[str, float]]:
    ab = _minutes(truth, lo, hi)
    if not ab:
        return {}
    a, b = ab
    return {t: {p: round(b["teams"][t]["plan"][p] - a["teams"][t]["plan"][p], 3) for p in PARAMS} for t in a["teams"]}


def hidden_swing(truth: dict[str, Any], gainer: str, anchor: int, now: int) -> float:
    """How far the hidden state moved toward `gainer` from the 15 minutes before the anchor to the
    minutes since it: flow, plus attacking intent in the plans."""
    mins = {r["m"]: r for r in truth["minutes"]}
    loser = next(t for t in truth["minutes"][0]["teams"] if t != gainer)

    def push(m: int) -> float | None:
        r = mins.get(m)
        if r is None:
            return None
        total = 0.0
        for t, sign in ((gainer, 1), (loser, -1)):
            p = r["teams"][t]["plan"]
            total += sign * (float(r["teams"][t]["flow"]) + 0.3 * (p["block"] + p["press"] + p["risk"]))
        return total

    def mean(lo: int, hi: int) -> float:
        v = [x for m in range(lo, hi) if (x := push(m)) is not None]
        return sum(v) / len(v) if v else 0.0

    return mean(anchor, now) - mean(anchor - 15, anchor)


def score_card(card: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    lo, hi = card["anchor"]["m"] - 4, card["at"] - 1
    moves = plan_moves(truth, lo, hi)
    plan_driven = any(abs(v) >= PLAN_MOVE for t in moves.values() for v in t.values())
    kind, team = card["cause"]["kind"], card["cause"].get("team")
    decisions = [d for d in truth["decisions"] if lo <= d["m"] < card["at"]]
    out: dict[str, Any] = {"kind": kind, "mode": card["mode"], "shifted": card["shifted"], "plan_driven": plan_driven}

    gainer = card["momentum"]["gainer"]
    if gainer:
        out["real_swing"] = hidden_swing(truth, gainer, card["anchor"]["m"], card["at"]) > 0

    if kind == "red_card_reshape":
        out["correct"] = any(d["kind"] in RESHAPES and d["team_id"] == team for d in decisions) or (
            team in moves and moves[team]["block"] <= -PLAN_MOVE
        )
    elif kind == "red_card_holding":
        out["correct"] = not any(d["kind"] in RESHAPES and d["team_id"] == team for d in decisions)
    elif kind == "chasing_the_game":
        out["correct"] = team in moves and any(abs(v) >= PLAN_MOVE for v in moves[team].values())
    elif kind == "fatigue":
        out["correct"] = any(
            d["kind"] == "fatigue_fade" and d["team_id"] == team and d["m"] <= card["at"] for d in truth["decisions"]
        )

    if card["mode"] == "event" and card["shifted"]:
        ids = set(card["anchor"]["event_ids"])
        backed = any(d["trigger"].get("event_id") in ids for d in decisions) or (
            card["anchor"]["label"] == "Since half-time" and any(d["trigger"]["kind"] == "half_time" for d in decisions)
        )
        out["event_backed"] = backed or plan_driven
    return out


def control(md: MatchData, truth: dict[str, Any], rng: random.Random, n: int = 6) -> list[dict[str, Any]]:
    """Random windows, with the 'gainer' being whichever side's field tilt happened to rise."""
    out = []
    home = md.teams[0]
    for _ in range(n):
        now = rng.randint(30, md.last_minute)
        anchor = now - 6
        after, before = tilt(md, home, anchor, now), tilt(md, home, anchor - 15, anchor)
        if after is None or before is None or after == before:
            continue
        gainer = home if after > before else md.opp(home)
        out.append({"control": True, "real_swing": hidden_swing(truth, gainer, anchor, now) > 0})
    return out


def _one(args: tuple[Path, Path]) -> list[dict[str, Any]]:
    folder, truth_file = args
    truth = json.loads(truth_file.read_text())
    md = load(folder)
    rows = [score_card(c, truth) for c in explain_match(md)["cards"]]
    return rows + control(md, truth, random.Random(folder.name))


def _agents(jobs: list[tuple[Path, Path]], runner_name: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Score the agent crew (matchlens/agents) instead of the deterministic Explainer."""
    import asyncio

    from ..agents.crew import explain_match_async
    from ..agents.interpreter import interpret_cards
    from ..agents.runners import make_runner
    from .director import direct

    async def one(runner: Any, folder: Path, truth_file: Path) -> list[dict[str, Any]]:
        truth = json.loads(truth_file.read_text())
        md = load(folder)
        cards = (await explain_match_async(md, runner))["cards"]
        shown = direct(cards)
        await interpret_cards(runner, md, shown)
        rows = [score_card(c, truth) | {"fallback": c["agents"]["fallback"]} for c in cards]
        rows += [interpretation(c) for c in shown]
        return rows + control(md, truth, random.Random(folder.name))

    async def go() -> tuple[list[dict[str, Any]], dict[str, Any]]:
        runner = make_runner(runner_name)
        try:
            done = await asyncio.gather(*(one(runner, f, t) for f, t in jobs))
            return [r for rs in done for r in rs], runner.usage.as_dict()
        finally:
            await runner.close()

    return asyncio.run(go())


def evaluate(out_dir: Path, runner: str | None = None) -> dict[str, Any]:
    """Score every match in a generated folder. `runner` scores the agent crew on that runner."""
    folders = sorted((out_dir / "matches").iterdir())
    jobs = [(f, out_dir / "truth" / f"{f.name}.json") for f in folders]
    if runner:
        rows, usage = _agents(jobs, runner)
        lines = [r for r in rows if r.get("interpreted")]
        rows = [r for r in rows if not r.get("interpreted")]
        report = summarise(rows, len(folders))
        cards = [r for r in rows if not r.get("control")]
        report["agents"] = {
            "runner": runner,
            "fallback_rate": _rate(cards, "fallback"),
            "interpreter": {
                "cards": len(lines),
                "passed_first_time": _rate(lines, "first_time"),
                "fell_back_to_rules": _rate(lines, "fallback"),
                "lines_repeating_a_stat_name": _rate([x for r in lines for x in r["repeats"]], "x"),
                "words_per_line": round(sum(r["words"] for r in lines) / max(1, len(lines)), 1),
            },
            "usage": usage,
        }
        return report
    with ProcessPoolExecutor() as pool:
        rows = [r for rs in pool.map(_one, jobs, chunksize=4) for r in rs]
    return summarise(rows, len(folders))


def interpretation(card: dict[str, Any]) -> dict[str, Any]:
    """How the Interpreter did on one card: did it pass, and do its lines read stats out?"""
    log = card["agents"]["interpreter"]
    labels = {s["label"].lower() for s in card["stats"]}
    text = list(card["text"].values())
    return {
        "interpreted": True,
        "first_time": bool(log["rounds"]) and log["rounds"][0]["status"] == "passed",
        "fallback": log["fallback"],
        "repeats": [{"x": any(lb in t.lower() for lb in labels)} for t in text],
        "words": sum(len(t.split()) for t in text) / max(1, len(text)),
    }


def _rate(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def summarise(rows: list[dict[str, Any]], n: int) -> dict[str, Any]:
    ctrl = [r for r in rows if r.get("control")]
    rows = [r for r in rows if not r.get("control")]
    shifts = [r for r in rows if r["shifted"]]
    spont = [r for r in shifts if r["mode"] in ("shift", "recovery")]
    claims = [r for r in rows if r.get("correct") is not None]
    by_claim: dict[str, list[bool]] = collections.defaultdict(list)
    for r in claims:
        by_claim[r["kind"]].append(r["correct"])
    return {
        "matches": n,
        "cards_per_match": round(len(rows) / n, 2),
        "shift_cards_per_match": round(len(shifts) / n, 2),
        "shifts_matching_a_hidden_swing": _rate(shifts, "real_swing"),
        "random_windows_matching_a_hidden_swing": _rate(ctrl, "real_swing"),
        "spontaneous_shifts_with_a_hidden_plan_change": _rate(spont, "plan_driven"),
        "event_shifts_backed_by_truth": _rate([r for r in rows if "event_backed" in r], "event_backed"),
        "cause_claims_checked": len(claims),
        "cause_claims_correct": _rate(claims, "correct"),
        "by_claim": {k: {"n": len(v), "correct": round(sum(v) / len(v), 3)} for k, v in sorted(by_claim.items())},
        "causes": dict(collections.Counter(r["kind"] for r in rows).most_common()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Score the explainer against hidden truth on fresh matches")
    ap.add_argument("--matches", type=int, default=100)
    ap.add_argument("--seed", type=int, default=9000, help="season seed; 2026 was used for tuning")
    ap.add_argument("--data", type=Path, help="score an existing generated folder instead")
    ap.add_argument("--check", action="store_true", help="exit non-zero if a headline number falls below its floor")
    ap.add_argument("--agents", choices=["offline", "foundry"], help="score the agent crew on this runner instead")
    args = ap.parse_args()
    if args.data:
        report = evaluate(args.data, args.agents)
    else:
        from ..gen.cli import write_season

        with tempfile.TemporaryDirectory() as tmp:
            write_season(Path(tmp), args.seed, args.matches)
            report = evaluate(Path(tmp), args.agents)
    print(json.dumps(report, indent=1))
    if args.check:
        failed = check(report)
        for f in failed:
            print("FAIL", f)
        raise SystemExit(1 if failed else 0)


def check(report: dict[str, Any]) -> list[str]:
    """Floors for CI: shifts must track the hidden state better than chance, and claims must hold up."""
    out = []
    lift = (report["shifts_matching_a_hidden_swing"] or 0) - (report["random_windows_matching_a_hidden_swing"] or 0)
    if lift < 0.05:
        out.append(f"shifts beat random windows by only {lift:.3f}")
    if (report["event_shifts_backed_by_truth"] or 0) < 0.75:
        out.append(f"event shifts backed by truth {report['event_shifts_backed_by_truth']}")
    if (report["cause_claims_correct"] or 0) < 0.65:
        out.append(f"cause claims correct {report['cause_claims_correct']}")
    return out


if __name__ == "__main__":
    main()
