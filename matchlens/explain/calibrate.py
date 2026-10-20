"""Separate a change of style from a side-effect of territory.

When a team pins the other back, its defensive actions happen higher up, it crosses more and it
wins more balls high: those numbers move because of the territory, not because the manager asked
for anything. For every style metric we learn, over random windows of unlabelled matches, how much
it moves with field tilt alone:

    z_metric = beta * z_tilt + residual

A style claim then rests on the residual (`style_sd`), the part territory does not explain. The
calibration uses only public tables, never truth.

    python -m matchlens.explain.calibrate --matches 120     # rewrites calibration.json
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st
import tempfile
from pathlib import Path

from .match import MatchData
from .metrics import BY_KEY, METRICS, change

PATH = Path(__file__).with_name("calibration.json")


def load_calibration() -> dict[str, dict[str, float]]:
    return json.loads(PATH.read_text()) if PATH.exists() else {}


def samples(md: MatchData, rng: random.Random, n: int = 12) -> list[dict[str, float]]:
    out = []
    for _ in range(n):
        now = rng.randint(28, md.last_minute)
        anchor = now - rng.randint(5, 12)
        base = [(0, anchor)]
        team = rng.choice(md.teams)
        tilt = change(md, BY_KEY["field_tilt"], team, anchor, now, base)
        if tilt is None:
            continue
        row = {"_tilt": tilt.effect_sd}
        for m in METRICS:
            c = change(md, m, team, anchor, now, base)
            if c is not None:
                row[m.key] = c.effect_sd
        out.append(row)
    return out


def fit(rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    out = {}
    for m in METRICS:
        pairs = [(r["_tilt"], r[m.key]) for r in rows if m.key in r]
        if len(pairs) < 50:
            continue
        xs, ys = zip(*pairs, strict=True)
        beta = sum(x * y for x, y in pairs) / sum(x * x for x in xs)
        resid = [y - beta * x for x, y in pairs]
        out[m.key] = {"beta": round(beta, 3), "resid_sd": round(max(st.pstdev(resid), 0.3), 3), "raw_sd": round(st.pstdev(ys), 3)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Learn how much each style metric moves with territory alone")
    ap.add_argument("--matches", type=int, default=120)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    from ..gen.cli import write_season
    from .match import load

    rng = random.Random(args.seed)
    rows: list[dict[str, float]] = []
    with tempfile.TemporaryDirectory() as tmp:
        write_season(Path(tmp), args.seed, args.matches)
        for folder in sorted((Path(tmp) / "matches").iterdir()):
            rows += samples(load(folder), rng)
    cal = fit(rows)
    PATH.write_text(json.dumps(cal, indent=1) + "\n")
    print(json.dumps(cal, indent=1))


if __name__ == "__main__":
    main()
