"""The unseen-match test: would a match we have never seen, arriving live from someone else's feed,
just work?

For each test match:

1. Generate a fresh match (new seed, new pairing) that nothing was tuned on.
2. Send it the way a provider would: per-minute club and player tables plus key events only,
   with the provider's own column names (mappings/example-provider.json), no final score and no
   raw event stream. Its hidden truth stays behind.
3. Play the feed through the adapter and the live runner, one minute at a time.
4. Separately, explain the original match folder in one go, the way the demo bundles are made.

It passes when:

- **tables**: the adapter rebuilt exactly the tables the original match has;
- **numbers**: every number on every card going on screen, recomputed from the original
  match's events, is the same;
- **no look-ahead**: the live run raised the same moments, made the same cards and put the same
  ones on screen as the one-go run, though it never had a minute it hadn't reached; and
- **causes**: scored against the hidden truth, the live cards clear the same floors as the usual
  explainer test (swing-explain-eval --check), once there are enough matches to judge.

    swing-feed unseen                         # 30 matches, deterministic rules (about 2 min)
    swing-feed unseen --matches 6             # the quick version CI runs
    swing-feed unseen --agents foundry        # also run one match through the agents on Foundry
"""

from __future__ import annotations

import asyncio
import json
import random
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from ..explain.director import direct
from ..explain.evaluate import check, control, score_card, summarise
from ..explain.explainer import _stat_out, explain_match
from ..explain.match import MatchData, load
from ..explain.specialists import investigate
from ..explain.watcher import Moment, watch
from .feed import export_feed, load_mapping, read_feed
from .runner import LiveRunner, crew, play

SEED = 5150  # tuning used season seed 2026 and the explainer test 9000; the demo uses 31-36
MIN_FOR_FLOORS = 20  # matches needed before the cause floors mean anything
TOL = 0.011


def fixtures(n: int, seed: int) -> list[tuple[str, str, int]]:
    from ..gen.model import load_league

    clubs = [c["team_id"] for c in load_league()["clubs"]]
    rng = random.Random(seed)
    out = []
    for i in range(n):
        home, away = rng.sample(clubs, 2)
        out.append((home, away, seed * 1000 + i))
    return out


def make_match(home: str, away: str, seed: int, out: Path) -> tuple[Path, Path]:
    """Generate one match into out/matches/<id>, its truth into out/truth/<id>.json."""
    from ..gen import generate_match
    from ..gen.cli import write_one

    m = generate_match(home, away, seed, match_id=f"unseen-{home}-{away}-{seed}")
    folder = write_one(out, m.match_id, m.home, m.away, m.seed, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes)
    return folder, out / "truth" / f"{m.match_id}.json"


def _key(m: Moment) -> tuple[int, int, str]:
    return (m.now, m.anchor_m, m.mode)


def same_tables(live: MatchData, ref: MatchData) -> list[str]:
    out = []
    if live.team != ref.team:
        out.append("club tables differ")
    if live.player != ref.player:
        out.append("player tables differ")
    if live.clocks != ref.clocks:
        out.append("match clock differs")
    if [vars(k) for k in live.key_events] != [vars(k) for k in ref.key_events]:
        out.append("key events differ")
    return out


def verify_numbers(ref: MatchData, moments: dict[tuple[int, int, str], Moment], card: dict[str, Any]) -> list[str]:
    """Recompute a card's numbers from the original match and compare."""
    where = f"card at {card['clock']}"
    m = moments.get((card["at"], card["anchor"]["m"], card["mode"]))
    if m is None:
        return [f"{where}: the one-go Watcher raised no such moment"]
    out = []
    if (
        abs(card["momentum"]["before"] - round(m.momentum_before, 1)) > TOL
        or abs(card["momentum"]["now"] - round(m.momentum_now, 1)) > TOL
    ):
        out.append(f"{where}: momentum {card['momentum']['before']}->{card['momentum']['now']} does not recompute")
    md = ref.until(m.now)
    found = investigate(md, m)
    recomputed = [_stat_out(md, f) for fs in found.values() for f in fs if "label" in f and "before" in f and "after" in f]
    for s in card["stats"]:
        if not any(
            r["label"] == s["label"]
            and r["team"] == s["team"]
            and r.get("player") == s.get("player")
            and abs(float(r["before"]) - float(s["before"])) <= TOL
            and abs(float(r["after"]) - float(s["after"])) <= TOL
            for r in recomputed
        ):
            who = s.get("name") or s["team"]
            out.append(f"{where}: {who} {s['label']} {s['before']}->{s['after']} does not recompute")
    return out


def _view(cards: list[dict[str, Any]]) -> str:
    return json.dumps(cards, sort_keys=True)


def check_one(folder: Path, truth_file: Path, feed_dir: Path) -> dict[str, Any]:
    """Run one unseen match live from its feed and in one go from its folder, and compare."""
    feed = read_feed(feed_dir)
    live = asyncio.run(play(feed.meta, feed.minutes))
    ref = load(folder)
    one_go = explain_match(ref)
    one_go_shown = direct(one_go["cards"])
    one_go_moments = watch(ref)
    moments = {_key(m): m for m in one_go_moments}
    problems = same_tables(live.match.md, ref)
    for c in live.shown:
        problems += verify_numbers(ref, moments, c)
    if [_key(m) for m in live.moments] != [_key(m) for m in one_go_moments]:
        problems.append("the live Watcher raised different moments")
    if _view(live.cards) != _view(one_go["cards"]):
        problems.append("the live cards differ from the one-go cards")
    if [(c["at"], c["anchor"]["m"]) for c in live.shown] != [(c["at"], c["anchor"]["m"]) for c in one_go_shown]:
        problems.append("the live Director put different cards on screen")
    truth = json.loads(truth_file.read_text())
    rows = [score_card(c, truth) for c in live.cards] + control(ref, truth, random.Random(folder.name))
    (h, a), (gh, ga) = ref.teams, ref.meta["final_score"]
    return {
        "match_id": ref.meta["match_id"],
        "score": f"{ref.short(h)} {gh}-{ga} {ref.short(a)}",
        "minutes": live.match.minutes,
        "candidates": len(live.cards),
        "on_screen": len(live.shown),
        "numbers_checked": sum(len(c["stats"]) for c in live.shown),
        "missing_columns": sorted(live.match.missing),
        "problems": problems,
        "rows": rows,
    }


def _check_one(args: tuple[Path, Path, Path]) -> dict[str, Any]:
    return check_one(*args)


def check_agents(folder: Path, truth_file: Path, feed_dir: Path, runner_name: str) -> dict[str, Any]:
    """One unseen match through the agent crew, live. The models choose, so the cards can differ from
    the rules; what must hold is the numbers, the moments and the Director's choices."""
    from ..agents.runners import make_runner

    async def go() -> tuple[LiveRunner, dict[str, Any]]:
        runner = make_runner(runner_name)
        try:
            explainer, finish = crew(runner)
            feed = read_feed(feed_dir)
            live = await play(feed.meta, feed.minutes, explainer, finish)
            return live, runner.usage.as_dict()
        finally:
            await runner.close()

    live, usage = asyncio.run(go())
    ref = load(folder)
    one_go_moments = watch(ref)
    moments = {_key(m): m for m in one_go_moments}
    problems = same_tables(live.match.md, ref)
    if [_key(m) for m in live.moments] != [_key(m) for m in one_go_moments]:
        problems.append("the live Watcher raised different moments")
    for c in live.shown:
        problems += verify_numbers(ref, moments, c)
    replay = direct(json.loads(_view(live.cards)))
    if [(c["at"], c["anchor"]["m"]) for c in live.shown] != [(c["at"], c["anchor"]["m"]) for c in replay]:
        problems.append("the live Director chose differently from a one-go Director over the same cards")
    truth = json.loads(truth_file.read_text())
    scored = [score_card(c, truth) for c in live.cards]
    claims = [r["correct"] for r in scored if r.get("correct") is not None]
    return {
        "match_id": ref.meta["match_id"],
        "runner": runner_name,
        "candidates": len(live.cards),
        "on_screen": len(live.shown),
        "numbers_checked": sum(len(c["stats"]) for c in live.shown),
        "fallbacks": sum(1 for c in live.cards if c["agents"]["fallback"]),
        "causes": [c["cause"]["kind"] for c in live.cards],
        "cause_claims_checked": len(claims),
        "cause_claims_correct": sum(claims),
        "shifts_matching_a_hidden_swing": [r["real_swing"] for r in scored if "real_swing" in r],
        "usage": usage,
        "cards": [
            {"clock": c["clock"], "anchor": c["anchor"]["label"], "cause": c["cause"]["kind"], "text": c.get("text", {})}
            for c in live.shown
        ],
        "problems": problems,
    }


def run(matches: int = 30, seed: int = SEED, agents: str | None = None, keep: Path | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        root = keep or Path(tmp)
        jobs = []
        for home, away, s in fixtures(matches, seed):
            folder, truth = make_match(home, away, s, root / "source")
            jobs.append((folder, truth, export_feed(folder, root / "feed" / folder.name, load_mapping())))
        with ProcessPoolExecutor() as pool:
            results = list(pool.map(_check_one, jobs))
        rows = [r for res in results for r in res.pop("rows")]
        causes = summarise(rows, len(results))
        floors = check(causes) if matches >= MIN_FOR_FLOORS else []
        report: dict[str, Any] = {
            "matches": len(results),
            "seed": seed,
            "passed": not floors and not any(r["problems"] for r in results),
            "numbers_checked": sum(r["numbers_checked"] for r in results),
            "cards_on_screen": sum(r["on_screen"] for r in results),
            "causes": causes,
            "cause_floors": floors if matches >= MIN_FOR_FLOORS else f"not judged under {MIN_FOR_FLOORS} matches",
            "per_match": results,
        }
        if agents:
            a = check_agents(*jobs[0], agents)
            report["agents"] = a
            report["passed"] = report["passed"] and not a["problems"]
        return report
