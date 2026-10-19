"""Calibration: simulate many matches and compare per-match averages with real-world ranges.

The target ranges are approximate figures for a top-flight European league season, the
kind widely reported by public data providers. They are a sanity check that the
synthetic data looks like football, not a claim to match any specific league.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

TARGETS: dict[str, tuple[float, float, str]] = {
    "goals": (2.4, 3.2, "Goals per match"),
    "shots": (21.0, 28.0, "Shots per match"),
    "shots_on_target": (7.0, 10.0, "Shots on target per match"),
    "xg_per_shot": (0.09, 0.13, "Average xG per shot"),
    "passes": (800.0, 1050.0, "Passes per match (open play and restarts)"),
    "pass_accuracy": (0.78, 0.86, "Pass completion"),
    "corners": (8.5, 11.5, "Corners per match"),
    "fouls": (18.0, 25.0, "Fouls per match"),
    "yellow_cards": (3.0, 4.5, "Yellow cards per match"),
    "red_cards": (0.05, 0.25, "Red cards per match (straight or second yellow)"),
    "offsides": (2.5, 5.0, "Offsides per match"),
    "throw_ins": (32.0, 50.0, "Throw-ins per match"),
    "home_win_share": (0.40, 0.50, "Home wins"),
    "draw_share": (0.20, 0.30, "Draws"),
    "ball_in_play_min": (52.0, 62.0, "Ball in play, minutes"),
    "match_length_min": (93.0, 101.0, "Match length incl. added time, minutes"),
}
"""``key: (low, high, label)`` per-match ranges."""

UNTARGETED: dict[str, str] = {
    "xg": "xG per match (both teams)",
    "big_chances": "Big chances (xG 0.30 or more) per match",
    "goal_kicks": "Goal kicks per match",
    "tackles": "Tackles per match",
}
"""Reported for context; public figures vary too much by source to set a range."""


@dataclass
class MatchStats:
    values: dict[str, float]
    score: tuple[int, int]


def match_stats(events: Iterable[dict[str, Any]]) -> MatchStats:
    """Headline counts for one match from its events."""
    evs = list(events)
    counts: Counter[str] = Counter()
    passes = complete = 0
    xg_total = 0.0
    big = 0
    score = (0, 0)
    in_play = 0.0
    for e in evs:
        et, outcome = e["type"], e.get("outcome")
        q = e.get("qualifiers", {})
        if et == "period_end":
            in_play += q.get("ball_in_play_s", 0.0)
        if et in ("pass", "throw_in", "goal_kick", "free_kick", "corner", "kick_off"):
            passes += 1
            complete += outcome == "complete"
        if et == "shot":
            counts["shots"] += 1
            xg_total += q.get("xg", 0.0)
            big += bool(q.get("big_chance"))
            if outcome in ("goal", "saved"):
                counts["shots_on_target"] += 1
        if et == "goal":
            score = (q["score_home"], q["score_away"])
        if et == "card":
            counts["yellow_cards"] += outcome == "yellow"
            counts["red_cards"] += outcome in ("red", "second_yellow")
            counts["yellow_cards"] += outcome == "second_yellow"
        if et == "corner":
            counts["corners"] += 1
        if et in ("foul", "offside", "tackle"):
            counts[{"foul": "fouls", "offside": "offsides", "tackle": "tackles"}[et]] += 1
        if et == "throw_in":
            counts["throw_ins"] += 1
        if et == "goal_kick":
            counts["goal_kicks"] += 1
    values = {k: float(v) for k, v in counts.items()}
    values["goals"] = float(sum(score))
    values["passes"] = float(passes)
    values["pass_accuracy"] = complete / passes if passes else 0.0
    values["xg"] = xg_total
    values["xg_per_shot"] = xg_total / counts["shots"] if counts["shots"] else 0.0
    values["big_chances"] = float(big)
    values["ball_in_play_min"] = in_play / 60
    values["match_length_min"] = (evs[-1]["t"] if evs else 0.0) / 60
    for key in (*TARGETS, *UNTARGETED):
        values.setdefault(key, 0.0)
    return MatchStats(values, score)


def summarise(stats: list[MatchStats]) -> dict[str, float]:
    """Average each statistic across matches; result shares from the scores."""
    out = {
        key: statistics.fmean(s.values[key] for s in stats)
        for key in (*TARGETS, *UNTARGETED)
        if key not in ("home_win_share", "draw_share")
    }
    n = len(stats)
    out["home_win_share"] = sum(s.score[0] > s.score[1] for s in stats) / n
    out["draw_share"] = sum(s.score[0] == s.score[1] for s in stats) / n
    return out


def report(summary: dict[str, float], n_matches: int) -> str:
    """A Markdown table of simulated averages against target ranges."""
    lines = [
        f"| Statistic | Simulated ({n_matches} matches) | Target range | In range |",
        "|---|---|---|---|",
    ]
    for key, (lo, hi, label) in TARGETS.items():
        v = summary[key]
        fmt = "{:.1%}" if key in ("pass_accuracy", "home_win_share", "draw_share") else "{:.2f}"
        rng = f"{fmt.format(lo)} to {fmt.format(hi)}"
        ok = "yes" if lo <= v <= hi else "no"
        lines.append(f"| {label} | {fmt.format(v)} | {rng} | {ok} |")
    for key, label in UNTARGETED.items():
        lines.append(f"| {label} | {summary[key]:.2f} | no target | |")
    return "\n".join(lines)
