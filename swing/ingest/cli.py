"""swing-feed: take a match as a live feed of per-minute tables.

    swing-feed export out/matches/ash-brk-7 feed/ash-brk-7     # write a match as a provider's feed
    swing-feed run feed/ash-brk-7                              # play it through, a minute at a time
    swing-feed run feed/ash-brk-7 --agents foundry --pace 2    # with the agents on Microsoft Foundry
    swing-feed unseen --matches 6                              # the unseen-match test

A feed is lineups.json, club_minutes.csv, player_minutes.csv and events.csv in the provider's own
column names; --mapping names the file that maps them onto ours (docs/live-feed.md).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from ..explain.match import MatchData
from .feed import export_feed, load_mapping, read_feed
from .runner import Explain, Finish, crew, play, rules
from .unseen import SEED
from .unseen import run as run_unseen


def _print_card(md: MatchData, c: dict[str, Any]) -> None:
    stats = "; ".join(
        f"{s.get('name') or md.short(s['team'])} {s['label']} {s['before']:g} -> {s['after']:g}" for s in c["stats"]
    )
    print(f"{c['clock']:>7}  ON SCREEN  {c['anchor']['label']}  [{c['cause']['kind']}]  {stats}", flush=True)


def _run(args: argparse.Namespace) -> None:
    feed = read_feed(args.feed, load_mapping(args.mapping))

    async def go() -> None:
        runner = None
        explainer: Explain = rules
        finish: Finish | None = None
        if args.agents:
            from ..agents.runners import make_runner

            runner = make_runner(args.agents)
            explainer, finish = crew(runner)
        try:
            live = await play(feed.meta, feed.minutes, explainer, finish, args.pace, _print_card)
        finally:
            if runner is not None:
                await runner.close()
        md, score = live.match.md, live.match.score
        h, a = md.teams
        print(
            f"Full time {md.short(h)} {score[h]}-{score[a]} {md.short(a)}: {live.match.minutes} minutes, "
            f"{len(live.cards)} candidate cards, {len(live.shown)} on screen."
        )
        if live.match.missing:
            print("columns the feed never sent:", ", ".join(sorted(live.match.missing)))
        if args.json:
            args.json.write_text(json.dumps(live.result(), indent=1) + "\n")

    asyncio.run(go())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write a match folder as a provider's feed")
    ex.add_argument("match", type=Path)
    ex.add_argument("out", type=Path)
    ex.add_argument("--mapping", type=Path)
    rn = sub.add_parser("run", help="play a feed through the live runner")
    rn.add_argument("feed", type=Path)
    rn.add_argument("--mapping", type=Path)
    rn.add_argument("--agents", choices=["offline", "foundry"], help="explain with the agent crew on this runner")
    rn.add_argument("--pace", type=float, default=0.0, help="seconds between minutes")
    rn.add_argument("--json", type=Path, help="write every card to this file")
    un = sub.add_parser("unseen", help="the unseen-match test")
    un.add_argument("--matches", type=int, default=30)
    un.add_argument("--seed", type=int, default=SEED)
    un.add_argument("--agents", choices=["offline", "foundry"], help="also run the first match through the agent crew")
    un.add_argument("--keep", type=Path, help="keep the generated matches and feeds here")
    un.add_argument("--json", type=Path, help="write the full report here")
    args = ap.parse_args()
    if args.cmd == "export":
        print(export_feed(args.match, args.out, load_mapping(args.mapping)))
    elif args.cmd == "run":
        _run(args)
    else:
        report = run_unseen(args.matches, args.seed, args.agents, args.keep)
        if args.json:
            args.json.write_text(json.dumps(report, indent=1) + "\n")
        for r in report["per_match"]:
            mark = "ok  " if not r["problems"] else "FAIL"
            print(
                f"{mark} {r['score']:<28} {r['on_screen']} on screen of {r['candidates']}, {r['numbers_checked']} numbers checked"
            )
            for p in r["problems"]:
                print("       ", p)
        c = report["causes"]
        print(
            f"\ncauses vs hidden truth: shifts matching a hidden swing {c['shifts_matching_a_hidden_swing']} "
            f"(random windows {c['random_windows_matching_a_hidden_swing']}), event shifts backed "
            f"{c['event_shifts_backed_by_truth']}, claims correct {c['cause_claims_correct']} of {c['cause_claims_checked']}"
        )
        print("cause floors:", report["cause_floors"] or "all met")
        if "agents" in report:
            a = report["agents"]
            print(
                f"\nagents ({a['runner']}) on {a['match_id']}: {a['on_screen']} on screen of {a['candidates']}, "
                f"{a['numbers_checked']} numbers checked, {a['fallbacks']} fallbacks, "
                f"claims correct {a['cause_claims_correct']} of {a['cause_claims_checked']}"
            )
            for p in a["problems"]:
                print("       ", p)
        print("\nPASS" if report["passed"] else "\nFAIL")
        raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
