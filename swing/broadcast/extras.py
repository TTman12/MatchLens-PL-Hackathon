"""What a bundle carries beyond the cards: the full-time recap, follow-a-player, the analyst view's
detail, and the Spanish screen.

- ``recap``: the full-time recap (swing/explain/recap.py).
- ``follow``: per player, his tags, involvement and full-time ranks (swing/explain/follow.py).
- ``stats.last15``: club stats over the last 15 minutes, minute by minute, for the analyst view.
- each card's ``detail``: both clubs before the card's anchor against since, on the stats analysts
  read, plus the card's cause and confidence.
- ``i18n.es``: stat labels, and each card's anchor, line and analysis lines in Spanish. The rules
  write the Spanish here; swing/agents/translator.py replaces them with checked translations
  of the English lines when a translator runs.

    swing-broadcast --demo 6 --out web/data --enrich   # add these to the bundles already there
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..explain import spanish
from ..explain.analysis import lever_line
from ..explain.follow import follow
from ..explain.insight import lines, reading
from ..explain.match import MatchData
from ..explain.metrics import BY_KEY as METRICS
from ..explain.recap import headlines, recap
from ..explain.specialists import PLAYER_STATS
from .tables import TEAM_STATS, _running

# the analyst's before-and-since table on each card (explain/metrics.py keys)
DETAIL = ("possession", "field_tilt", "final_third_passes", "shots", "xg", "defending_height", "ppda", "duels_won")
LAST = 15  # minutes in the analyst view's "last 15" column


def window(md: MatchData) -> Callable[[int, int], dict[str, dict[str, float]]]:
    """(lo, hi) -> each club's team-table stats over minutes [lo, hi)."""
    fns = {k: fn for k, _, _, fn, _ in TEAM_STATS}

    def values(lo: int, hi: int) -> dict[str, dict[str, float]]:
        lo, hi = max(lo, 0), min(hi, md.last_minute + 1)
        n = max(hi - lo, 0)
        cum = {t: _running(md.team[t][lo:hi], n) for t in md.teams}
        i = n - 1
        return {t: {k: (fn(cum[t], cum[md.opp(t)], i) if n else 0) for k, fn in fns.items()} for t in md.teams}

    return values


def last15(md: MatchData) -> dict[str, dict[str, list[float]]]:
    w = window(md)
    per_minute = [w(m + 1 - LAST, m + 1) for m in range(md.last_minute + 1)]
    return {t: {k: [v[t][k] for v in per_minute] for k, *_ in TEAM_STATS} for t in md.teams}


def _fmt(v: float | None, unit: str, key: str) -> str | None:
    if v is None:
        return None
    if unit.startswith("%"):
        return f"{v:.0f}%"
    if unit == "m":
        return f"{v:.0f}m"
    if v == 0:
        return "0"
    return f"{v:.2f}" if key == "xg" else f"{v:.1f}"


def detail(md: MatchData, card: dict[str, Any], confidence: float | None) -> dict[str, Any]:
    """Both clubs on the analysts' stats: before the anchor, and since it."""
    lo, hi = card["anchor_m"], card["at"]
    rows = []
    for key in DETAIL:
        mt = METRICS[key]
        vals = {t: [_fmt(mt.fn(md, t, 0, lo), mt.unit, key), _fmt(mt.fn(md, t, lo, hi), mt.unit, key)] for t in md.teams}
        if any(v is None for pair in vals.values() for v in pair):
            continue
        unit = "per 10'" if mt.unit == "per 10 min" else ""
        rows.append({"key": key, "label": mt.label, "unit": unit, "values": vals})
    return {"rows": rows, "minutes": hi - lo, "cause": card["cause"], "confidence": confidence}


# what a card's stat label is, for reading a bundle card back into facts
LABEL_METRIC = {m.label: m.key for m in METRICS.values()} | {"Sprints per player": "sprints"}
PLAYER_METRIC = {label: key for key, label, *_ in PLAYER_STATS}


def _number(v: str) -> float:
    return float(v.rstrip("%m") or 0)


def card_facts(md: MatchData, card: dict[str, Any]) -> dict[str, Any]:
    """The facts a bundle card's line is read from (insight.facts), from the card itself: for
    bundles written before the facts were kept, so the rules can write its Spanish line."""
    found = []
    for s in card["stats"]:
        before, after = _number(s["usual"]), _number(s["value"])
        f: dict[str, Any] = {
            "team": s["team"],
            "label": s["label"],
            "before": before,
            "after": after,
            "effect_sd": 1.0 if after >= before else -1.0,
        }
        if s.get("player"):
            f |= {"player": s["player"], "name": s["player"], "metric": PLAYER_METRIC.get(s["label"], s["label"])}
            if s.get("usual_label", "before") != "before":
                f |= {"replaced": True, "replaced_name": s["usual_label"].replace(" (off)", "")}
            else:
                f["claim"] = "player_change"
        else:
            f["metric"] = LABEL_METRIC.get(s["label"], s["label"])
        found.append(f)
    gainer = card["momentum"]["gainer"]
    cause = {"kind": card["cause"], "team": found[0]["team"] if found else gainer}
    key, about = reading(cause, found, gainer)
    goals = md.score_at(card["at"])
    return {
        "teams": {t: {"name": md.short(t), "goals": goals[t], "state": _state(goals, t, md.opp(t))} for t in md.teams},
        "gainer": gainer,
        "cause": card["cause"],
        "reading": {"key": key, "team": about},
        "stats": [
            {"team": f["team"], "metric": f["metric"], **({"player": f["name"]} if f.get("player") else {})} for f in found
        ],
    }


def _state(goals: dict[str, int], t: str, o: str) -> str:
    return "leading" if goals[t] > goals[o] else "behind" if goals[t] < goals[o] else "level"


def spanish_card(md: MatchData, card: dict[str, Any], fx: dict[str, Any] | None) -> dict[str, Any]:
    """The rules' Spanish for a bundle card: its anchor, its line and its analysis lines."""
    out: dict[str, Any] = {"anchor": spanish.anchor(card["anchor"]), "source": "rules"}
    if fx:
        out["text"] = lines(fx, "es")
    if card.get("analysis"):
        goals = md.score_at(card["at"])
        an = {}
        for lens, a in card["analysis"].items():
            t = a["team"]
            o = md.opp(t)
            fill = {"T": md.short(t), "O": md.short(o)}
            an[lens] = lever_line(a["lever"], lens == "neutral", _state(goals, t, o), fill, "es")
        out["analysis"] = an
    return out


def labels(b: dict[str, Any]) -> dict[str, str]:
    """Every stat label in the bundle, in Spanish."""
    seen = {d["label"] for d in b["stats"]["team_stats"] + b["stats"]["player_stats"]}
    for c in b["cards"]:
        seen |= {s["label"] for s in c["stats"]}
        seen |= {a["stat"]["label"] for a in (c.get("analysis") or {}).values()}
        seen |= {r["label"] for r in c.get("detail", {}).get("rows", [])}
    return {k: spanish.LABELS.get(k, k) for k in sorted(seen)}


def add(md: MatchData, b: dict[str, Any], explained: list[dict[str, Any]]) -> dict[str, Any]:
    """Add the extras to a bundle, in place. `explained` are the explained cards behind the bundle's
    cards (each with its facts), matched by minute; a card with no match gets no Spanish line from
    the rules and keeps its English one until a translator runs."""
    by_at = {c["at"]: c for c in explained}
    b["stats"]["last15"] = last15(md)
    w = window(md)
    for card in b["cards"]:
        src = by_at.get(card["at"])
        conf = (
            (card.get("hood") or {}).get("confidence")
            or ((src or {}).get("cause") or {}).get("confidence")
            or (card.get("detail") or {}).get("confidence")
        )
        card["detail"] = detail(md, card, conf)
        card["i18n"] = {"es": spanish_card(md, card, src.get("facts") if src else None)}
    r = recap(md, b["momentum"], b["half_time_m"], b["cards"], b["stats"], w)
    r["i18n"] = {"es": {"text": headlines(md, r["pattern"], "es"), "source": "rules"}}
    r["agents"] = None
    b["recap"] = r
    b["follow"] = follow(md, b["stats"])
    b["i18n"] = {"es": {"labels": labels(b)}}
    return b
