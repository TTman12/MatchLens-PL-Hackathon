"""The realism gate: generate a season and check every number against the real 2017-18 season.

matchlens-realism                     # 380 matches, writes docs/realism.md, exits 1 on failure
matchlens-realism --matches 120       # quicker, looser
matchlens-realism --real <wyscout>    # re-measure the real targets (needs the Wyscout download)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from ..gen.season import generate_season
from .agg import from_events, from_wyscout
from .metrics import compute

TARGETS = Path(__file__).with_name("targets.json")
ROOT = Path(__file__).resolve().parents[2]

# metric -> allowed absolute difference from the real season; None means shown but not gated
TOLERANCE: dict[str, float | None] = {
    "passes per team": 25,
    "pass accuracy": 0.015,
    "duels per team": 20,
    "shots per team": 1.2,
    "fouls per team": 1.5,
    "events per team": 60,
    "final-third events per 5 min": 3.0,
    "goals per match": 0.3,
    "reds per match": 0.06,
    "subs per team": 0.3,
    "home pass share SD across matches": 0.02,
    "home win rate": 0.05,
    "draw rate": 0.05,
    "team pass accuracy SD": 0.02,
    "shifts per match": 0.6,
    "shifts with no trigger": 0.06,
    "trigger enrichment: sub by gainer": 0.2,
    "trigger enrichment: half-time": 0.2,
    "trigger enrichment: goal by loser": 0.2,
    "noise-floor shifts per match": 0.25,
    "conceding team field-tilt change": 0.04,
    "red-card team pass-share change": 0.08,
    "red cards measured": None,
    "sub effect when losing (net field tilt)": None,
    "sub duels per min vs replaced player": 0.12,
    "half-time swing >= 20 pts share": 0.06,
    "late field tilt when winning": 0.04,
    "player activity 60-75 vs 0-60": 0.04,
    "sustained shift after random minute": 0.04,
    "sustained shift after conceding": 0.05,
    "sustained shift after a sub": 0.05,
    "gainer pre-swing dip (SD)": 0.15,
    "gainer defending height change in shift (SD)": 0.15,
}
NOTES = {
    "red cards measured": "count of usable red cards, small in both",
    "sub effect when losing (net field tilt)": "real value rests on a small control sample; shown for information",
}


def run(matches: int, seed: int) -> tuple[dict[str, float], list[dict[str, object]]]:
    season = generate_season(seed=seed, limit=matches)
    aggs = [from_events(m["match_id"], m["home"], m["away"], m["events"]) for m in season]
    return compute(aggs), season


def report(real: dict[str, float], syn: dict[str, float], matches: int, seed: int, seconds: float) -> tuple[str, bool]:
    rows, ok_all = [], True
    for k, rv in real.items():
        sv = syn.get(k, math.nan)
        tol = TOLERANCE.get(k)
        if tol is None:
            verdict = "info"
        else:
            ok = abs(sv - rv) <= tol
            ok_all &= ok
            verdict = "pass" if ok else "**FAIL**"
        rows.append(
            f"| {k} | {rv:.3f} | {sv:.3f} | {'±' + format(tol, 'g') if tol is not None else '-'} | {verdict} |"
            + (f" {NOTES[k]}" if k in NOTES else "")
        )
    passed = sum(1 for r in rows if "| pass |" in r)
    gated = sum(1 for k in real if TOLERANCE.get(k) is not None)
    head = [
        "# Realism gate",
        "",
        f"Generated {matches} matches (seed {seed}) in {seconds:.0f} s and measured them with the same code as the real "
        "Premier League 2017-18 season (Wyscout public data, CC BY 4.0). A number passes when it is within the tolerance of the "
        "real value. Regenerate with `matchlens-realism`.",
        "",
        f"**{passed} of {gated} gated numbers pass{' — all pass' if ok_all else ''}.**",
        "",
        "| Number | Real | Synthetic | Tolerance | Result |",
        "|---|---|---|---|---|",
    ]
    return "\n".join(head + rows) + "\n", ok_all


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matches", type=int, default=380)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "realism.md")
    ap.add_argument("--real", type=Path, help="Wyscout download folder; re-measures the real targets")
    args = ap.parse_args()
    if args.real:
        TARGETS.write_text(json.dumps(compute(from_wyscout(args.real)), indent=1) + "\n")
        print(f"wrote {TARGETS}")
    real = json.loads(TARGETS.read_text())
    t = time.time()
    syn, _ = run(args.matches, args.seed)
    text, ok = report(real, syn, args.matches, args.seed, time.time() - t)
    args.out.write_text(text)
    print(text)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
