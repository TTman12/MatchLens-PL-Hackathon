"""``matchlens-sim``: run the simulator from the command line.

matchlens-sim match --out out/match                  # one match, all files, validated
matchlens-sim match --storyline comeback --out out/comeback
matchlens-sim season --out data/season --workers 4   # league, season, results
matchlens-sim featured --season-dir data/season --storyline comeback --out out/featured
matchlens-sim calibrate --matches 380 --report docs/calibration.md
matchlens-sim scout --home ash --away brk --seeds 200
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

from matchlens.contracts import League, Season

from .calibration import match_stats, report, summarise
from .engine import MatchEngine
from .league import build_league
from .match import simulate_match, write_match
from .season import featured_context, generate_season, match_seed, write_results_csv
from .storyline import STORYLINES, get_storyline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="matchlens-sim", description="MatchLens match simulator")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("match", help="simulate one match and write its files")
    p.add_argument("--home", default="ash")
    p.add_argument("--away", default="brk")
    p.add_argument("--seed", type=int, default=1325)
    p.add_argument("--match-id", default="m001")
    p.add_argument("--matchday", type=int, default=1)
    p.add_argument("--storyline", help=f"one of {', '.join(STORYLINES)} or a JSON file")
    p.add_argument("--no-frames", action="store_true", help="skip frames.jsonl (fast)")
    p.add_argument("--out", type=Path, required=True)

    p = sub.add_parser(
        "season", help="generate the league and the season before the featured match"
    )
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--matchday", type=int, default=30, help="the featured (streamed) matchday")
    p.add_argument("--home", default="ash")
    p.add_argument("--away", default="brk")
    p.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    p.add_argument("--out", type=Path, required=True)

    p = sub.add_parser("featured", help="simulate the featured fixture of a generated season")
    p.add_argument("--season-dir", type=Path, required=True)
    p.add_argument("--seed", type=int, help="defaults to the season's seed for this match")
    p.add_argument("--storyline")
    p.add_argument("--no-frames", action="store_true")
    p.add_argument("--out", type=Path, required=True)

    p = sub.add_parser("calibrate", help="simulate many matches and compare with real ranges")
    p.add_argument("--matches", type=int, default=100)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--report", type=Path, help="write the Markdown table here")

    p = sub.add_parser("scout", help="rank seeds of one fixture by how dramatic the match is")
    p.add_argument("--home", default="ash")
    p.add_argument("--away", default="brk")
    p.add_argument("--seeds", type=int, default=100)
    p.add_argument("--start", type=int, default=0)

    args = parser.parse_args(argv)
    handler = {
        "match": _match,
        "season": _season,
        "featured": _featured,
        "calibrate": _calibrate,
        "scout": _scout,
    }[args.command]
    return handler(args)


def _match(args: argparse.Namespace) -> int:
    league = build_league()
    story = get_storyline(args.storyline) if args.storyline else None
    match = simulate_match(
        league, args.home, args.away, args.match_id, args.seed, args.matchday, storyline=story
    )
    paths = write_match(match, args.out, frames=not args.no_frames)
    _dump(args.out / "league.json", league.model_dump(mode="json"))
    _describe(match.engine.score, match.meta.home.team_id, match.meta.away.team_id, paths)
    return 0


def _season(args: argparse.Namespace) -> int:
    league = build_league()
    started = time.time()
    result = generate_season(
        league, args.seed, (args.home, args.away), args.matchday, workers=args.workers
    )
    args.out.mkdir(parents=True, exist_ok=True)
    _dump(args.out / "league.json", league.model_dump(mode="json"))
    _dump(args.out / "season.json", result.season.model_dump(mode="json", exclude_none=True))
    write_results_csv(result.results, args.out / "results.csv")
    _dump(
        args.out / "featured.json",
        {
            "match_id": result.featured.match_id,
            "matchday": result.featured.matchday,
            "home_id": result.featured.home,
            "away_id": result.featured.away,
            "seed": match_seed(args.seed, result.featured.match_id),
            "season_seed": args.seed,
            "unavailable": sorted(result.featured_unavailable),
        },
    )
    print(
        f"Played {len(result.results)} matches in {time.time() - started:.0f}s; "
        f"wrote {args.out}/league.json, season.json, results.csv, featured.json"
    )
    return 0


def _featured(args: argparse.Namespace) -> int:
    league = League.model_validate_json((args.season_dir / "league.json").read_text("utf-8"))
    season = Season.model_validate_json((args.season_dir / "season.json").read_text("utf-8"))
    info = json.loads((args.season_dir / "featured.json").read_text("utf-8"))
    notes, win_prob = featured_context(league, season, info["home_id"], info["away_id"])
    story = get_storyline(args.storyline) if args.storyline else None
    match = simulate_match(
        league,
        info["home_id"],
        info["away_id"],
        info["match_id"],
        args.seed if args.seed is not None else info["seed"],
        info["matchday"],
        storyline=story,
        unavailable=frozenset(info["unavailable"]),
        stakes_notes=notes,
        win_prob=win_prob,
    )
    paths = write_match(match, args.out, frames=not args.no_frames)
    _dump(args.out / "league.json", league.model_dump(mode="json"))
    _dump(args.out / "season.json", season.model_dump(mode="json", exclude_none=True))
    _describe(match.engine.score, info["home_id"], info["away_id"], paths)
    return 0


def _calibrate(args: argparse.Namespace) -> int:
    league = build_league()
    ids = [c.team_id for c in league.clubs]
    rng = random.Random(args.seed)
    stats = []
    for i in range(args.matches):
        home, away = rng.sample(ids, 2)
        result = MatchEngine(league, home, away, f"m{i + 1:03d}", rng.randrange(2**31)).run()
        stats.append(match_stats(result.events))
    table = report(summarise(stats), args.matches)
    print(table)
    if args.report:
        args.report.write_text(table + "\n", encoding="utf-8")
    return 0


def _scout(args: argparse.Namespace) -> int:
    league = build_league()
    scored = []
    for seed in range(args.start, args.start + args.seeds):
        result = MatchEngine(league, args.home, args.away, "m001", seed).run()
        scored.append((drama(result.events), seed, result.score))
    scored.sort(reverse=True)
    print("score  seed  result")
    for score, seed, (h, a) in scored[:10]:
        print(f"{score:5.1f}  {seed:4d}  {h}-{a}")
    return 0


def drama(events: list[dict[str, Any]]) -> float:
    """How good a demo a match makes: lead changes, late goals, comebacks, red cards."""
    score = [0, 0]
    leader = 0
    points = 0.0
    behind_then_won = [False, False]
    for e in events:
        if e["type"] == "goal":
            score = [e["qualifiers"]["score_home"], e["qualifiers"]["score_away"]]
            points += 1.0
            minute = e["t"] / 60
            if minute > 80:
                points += 1.5
            now = (score[0] > score[1]) - (score[0] < score[1])
            if now != leader and now != 0:
                points += 1.0
            for x in (0, 1):
                if score[x] < score[1 - x]:
                    behind_then_won[x] = True
            leader = now
        if e["type"] == "card" and e.get("outcome") in ("red", "second_yellow"):
            points += 1.5
    winner = 0 if score[0] > score[1] else 1 if score[1] > score[0] else None
    if winner is not None and behind_then_won[winner]:
        points += 3.0
    return points


def _describe(score: tuple[int, int], home: str, away: str, paths: dict[str, Path]) -> None:
    files = ", ".join(str(p) for p in paths.values())
    print(f"{home} {score[0]}-{score[1]} {away}; wrote {files}")


def _dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
