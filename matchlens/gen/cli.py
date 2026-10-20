"""matchlens-gen: write synthetic matches in the public format.

    matchlens-gen match --home ash --away brk --seed 7            # one match into out/matches/<id>/
    matchlens-gen season --limit 40                                # many matches in parallel
    matchlens-gen clubs                                            # list the fictional clubs

Ground truth (the coaching decisions behind each match) goes to out/truth/<id>.json, outside the
match folder, so a system reading the match cannot see it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..data.io import write_match
from . import generate_match
from .model import load_league
from .season import generate_season


def match_meta(match_id: str, home: Any, away: Any, seed: int, events: list[dict[str, Any]]) -> dict[str, Any]:
    goals = {home.team_id: 0, away.team_id: 0}
    for e in events:
        if e["type"] == "shot" and e["outcome"] == "goal":
            goals[e["team_id"]] += 1
    return {
        "match_id": match_id,
        "competition": "MatchLens League (fictional)",
        "synthetic": True,
        "seed": seed,
        "venue": next((c.get("stadium") for c in load_league()["clubs"] if c["team_id"] == home.team_id), None),
        "teams": [home.meta(), away.meta()],
        "final_score": [goals[home.team_id], goals[away.team_id]],
        "physical_note": "distance_m, hsr_m and sprints are modelled, not measured",
        "coordinates": "metres, 105 x 68, acting team's attacking frame (own goal line x=0)",
    }


def write_one(
    out: Path,
    match_id: str,
    home: Any,
    away: Any,
    seed: int,
    events: list[dict[str, Any]],
    physical: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    minutes: list[dict[str, Any]],
) -> Path:
    folder = out / "matches" / match_id
    write_match(folder, match_meta(match_id, home, away, seed, events), events, physical)
    truth = out / "truth"
    truth.mkdir(parents=True, exist_ok=True)
    (truth / f"{match_id}.json").write_text(
        json.dumps({"match_id": match_id, "decisions": decisions, "minutes": minutes}, indent=1)
    )
    return folder


def write_season(out: Path, seed: int = 2026, limit: int | None = None) -> None:
    from .model import build_team

    clubs = {c["team_id"]: c for c in load_league()["clubs"]}
    for rec in generate_season(seed=seed, limit=limit):
        home, away = build_team(clubs[rec["home"]], True), build_team(clubs[rec["away"]], False)
        write_one(out, rec["match_id"], home, away, rec["seed"], rec["events"], rec["physical"], rec["decisions"], rec["minutes"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    one = sub.add_parser("match")
    one.add_argument("--home", required=True)
    one.add_argument("--away", required=True)
    one.add_argument("--seed", type=int, default=1)
    one.add_argument("--out", type=Path, default=Path("out"))
    many = sub.add_parser("season")
    many.add_argument("--seed", type=int, default=2026)
    many.add_argument("--limit", type=int)
    many.add_argument("--out", type=Path, default=Path("out"))
    sub.add_parser("clubs")
    args = ap.parse_args()

    if args.cmd == "clubs":
        for c in load_league()["clubs"]:
            print(f"{c['team_id']}  {c['name']:24s} rating {c['rating']}  {c['formation']}")
        return
    if args.cmd == "match":
        m = generate_match(args.home, args.away, args.seed)
        folder = write_one(
            args.out, m.match_id, m.home, m.away, args.seed, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes
        )
        print(f"{folder}  {m.home.short_name} {m.home.score}-{m.away.score} {m.away.short_name}  {len(m.events)} events")
        return
    write_season(args.out, args.seed, args.limit)
    print(f"wrote {args.limit or 380} matches to {args.out}/matches")


if __name__ == "__main__":
    main()
