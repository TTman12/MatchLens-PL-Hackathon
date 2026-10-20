"""The Explainer: reads every specialist's findings, settles on a cause, and picks the 1 or 2 stats
that show it best. It may conclude there is no single cause ("ebb and flow").

This is the deterministic reference. An LLM agent can take its place and reason over the same
findings, but numbers only ever come from the findings, and the Verifier rechecks them.
"""

from __future__ import annotations

from typing import Any

from .match import MatchData
from .specialists import Finding, investigate
from .stories import SHARES as LONE_SHARES
from .stories import compose, find_stories, match_story
from .watcher import Moment, watch

EASY = {"possession", "duels_won", "defending_height", "shots", "long_balls", "distance", "sprints", "high_turnovers", "xg"}
STRONG = 2.0  # effect, in random-window spreads, that counts as a clear change
CONTROL = "field_tilt"
SHARES = {"possession", "field_tilt"}
OFF_SCREEN = {CONTROL, "hsr"}  # the bar already shows tilt; high-speed metres per player reads as jargon
SWING_FULL = 40.0  # a field-tilt swing this big is as salient as a card gets  # the momentum bar already shows this one


def _aligned(f: Finding, gainer: str | None) -> float:
    pol = f.get("polarity", 0)
    if gainer is None or pol == 0:
        return 0.85
    sign = 1 if f["team"] == gainer else -1
    return 1.0 if f["effect_sd"] * pol * sign > 0 else 0.35


def _score(f: Finding, gainer: str | None) -> float:
    easy = 1.0 if f["metric"] in EASY or f["agent"] != "team_play" else 0.85
    return float(abs(f["effect_sd"]) * easy * _aligned(f, gainer))


def driver(m: Moment, team: list[Finding]) -> Finding | None:
    """The control stat that moved most in the direction of the shift: where the momentum came from."""
    pool = [f for f in team if f["polarity"] and f["metric"] != CONTROL and _aligned(f, m.gainer) == 1.0 and _visible(f)]
    pool.sort(key=lambda f: -abs(f["effect_sd"]))
    return pool[0] if pool and abs(pool[0]["effect_sd"]) >= STRONG / 2 else None


def decide_cause(md: MatchData, m: Moment, found: dict[str, list[Finding]]) -> tuple[dict[str, Any], Finding | None]:
    """Return (cause, the stat that best carries it).

    Only claims that stats can support are made. A manager's in-game tweak is usually too subtle to
    read from 10 minutes of numbers (see docs/explainer.md), so a shift with no event is described
    by what changed in play, not put down to an instruction nobody can see.
    """
    team = found["team_play"]
    lead_kind = m.events[0].kind if m.events else None
    drv = driver(m, team) if m.gainer else None
    play = {"kind": "play_change", "team": m.gainer, "driver": drv["family"] if drv else None}

    if lead_kind == "red_card":
        red_team = m.events[0].team_id
        cands = [f for f in team if f["team"] == red_team and f["metric"] in ("passes", "defending_height", "possession")]
        cands.sort(key=lambda f: f["effect_sd"])
        pick = cands[0] if cands and cands[0]["effect_sd"] <= -STRONG * 0.75 else None
        return {"kind": "red_card_reshape" if pick else "red_card_holding", "team": red_team}, pick

    if lead_kind == "goal":
        scorer = m.events[0].team_id
        if m.gainer is None:
            return {"kind": "goal_no_reaction", "team": scorer}, None
        kind = "chasing_the_game" if m.gainer != scorer else "goal_lift"
        return {"kind": kind, "team": m.gainer, "driver": play["driver"]}, drv

    if lead_kind == "substitution":
        subs = [f for f in found["substitutions"] if f["claim"] == "sub_vs_replaced" and abs(f["effect_sd"]) >= 2.5]
        subs = [f for f in subs if m.gainer in (None, f["team"])]
        if subs:
            best = max(subs, key=lambda f: abs(f["effect_sd"]))
            return {"kind": "substitution_impact", "team": best["team"], "player": best["player"]}, best
        if m.gainer is not None:
            return play, drv
        return {"kind": "sub_no_change", "team": m.events[0].team_id}, None

    if lead_kind == "half_time":
        return (play, drv) if m.gainer else ({"kind": "half_time_no_change", "team": None}, None)

    fades = [f for f in found["players"] if f["claim"] == "fatigue" and f["team"] != m.gainer]
    if fades:
        return {"kind": "fatigue", "team": fades[0]["team"]}, fades[0]
    if m.mode == "recovery":
        return {**play, "kind": "recovery"}, drv
    return play, drv


def _visible(f: Finding) -> bool:
    """A count shown on screen must differ from the usual by at least two to mean anything to a fan."""
    if f["unit"] != "per 10 min" or not f.get("minutes"):
        return True
    return bool(abs(f["after"] - f["before"]) * f["minutes"] / 10 >= 2)


def pick_stats(m: Moment, found: dict[str, list[Finding]], lead: Finding | None) -> list[Finding]:
    # individual numbers only go on screen when the cause is about that player (a sub, a fade);
    # one player's busy five minutes is noise next to what the team did
    pool = [f for f in found["team_play"] if f["metric"] not in OFF_SCREEN]
    pool = [f for f in pool if abs(f["effect_sd"]) >= 1.5 and _visible(f)]
    pool.sort(key=lambda f: -_score(f, m.gainer))
    chosen = [lead] if lead is not None else []
    for f in pool:
        if len(chosen) == 2:
            break
        if any(f is c or (f.get("family") and f.get("family") == c.get("family") and f["team"] == c["team"]) for c in chosen):
            continue
        if any(f["metric"] in SHARES and f["metric"] == c["metric"] for c in chosen):  # one side's share is the other's
            continue
        if any(f["metric"] == c["metric"] for c in chosen):  # two rows never repeat a stat
            continue
        chosen.append(f)
    return chosen


STORY_CAUSES = {"play_change", "recovery", "goal_lift", "chasing_the_game"}
# a player clearly doing more for the side that gained: his name goes on the card
STANDOUT_METRICS = {"defensive_actions", "duels_won", "progressive_passes", "sprints", "distance_m"}
STANDOUT = 3.5


def stands_out(f: Finding, gainer: str | None) -> bool:
    return bool(
        f.get("claim") == "player_change"
        and f["team"] == gainer
        and f["metric"] in STANDOUT_METRICS
        and f["after"] > f["before"]
        and f["effect_sd"] >= STANDOUT
        and _visible(f)
    )


def standouts(m: Moment, found: dict[str, list[Finding]]) -> list[Finding]:
    """Up to two players on the side that gained who are clearly doing more, one stat each."""
    pool = sorted((f for f in found["players"] if stands_out(f, m.gainer)), key=lambda f: -f["effect_sd"])
    out: list[Finding] = []
    for f in pool:
        if len(out) < 2 and all(f["player"] != o["player"] and f["metric"] != o["metric"] for o in out):
            out.append(f)
    return out


def _partner(m: Moment, found: dict[str, list[Finding]], chosen: list[Finding]) -> Finding | None:
    """A second stat for a share shown alone: possession on its own explains nothing."""
    pool = [
        f
        for f in found["team_play"]
        if f["metric"] not in OFF_SCREEN
        and abs(f["effect_sd"]) >= 1.0
        and _visible(f)
        and all(f["metric"] != c["metric"] and f.get("family") != c.get("family") for c in chosen)
        and f["metric"] not in LONE_SHARES
    ]
    pool.sort(key=lambda f: (f["team"] != chosen[0]["team"], -_score(f, m.gainer)))
    return pool[0] if pool else None


def choose_stats(m: Moment, cause: dict[str, Any], found: dict[str, list[Finding]], lead: Finding | None) -> list[Finding]:
    """The one or two numbers for the card. A play-style story (two stats that together say how the
    play changed) beats two unrelated numbers, and a share like possession never stands alone."""
    if cause["kind"] in STORY_CAUSES:
        stories = [s for s in find_stories(found["team_play"], m.gainer) if s["aligned"]]
        if stories:
            return list(stories[0]["stats"])
        stars = standouts(m, found)
        if stars:
            return stars
    stats = pick_stats(m, found, lead) or fallback_stats(m, found)
    if len(stats) == 1 and stats[0]["metric"] in LONE_SHARES and not stats[0].get("player"):
        extra = _partner(m, found, stats)
        if extra is not None:
            stats.append(extra)
    return stats


def anchor_label(md: MatchData, m: Moment, cause: dict[str, Any] | None = None) -> str:
    if cause and cause["kind"] == "substitution_impact" and cause.get("player") and len(m.events) == 1:
        return f"Since {md.names.get(cause['player'], '')} came on"  # the sub the card is about
    if not m.events:
        return f"Since {md.clock_of(m.anchor_m)}"
    e = m.events[0]
    if e.kind == "half_time":
        return "Since half-time"
    if e.kind == "red_card":
        return f"Since {md.names.get(e.player_id or '', md.short(e.team_id or ''))} red card"
    if e.kind == "goal":
        return f"Since {md.short(e.team_id or '')} goal {e.clock}"
    if len(m.events) > 1:
        return f"Since {md.short(e.team_id or '')} {'double' if len(m.events) == 2 else 'triple'} change"
    return f"Since {md.names.get(e.player_id or '', '')} came on"


def _stat_out(md: MatchData, f: Finding) -> dict[str, Any]:
    """Rates are shown as counts over the window, against what was usual for that many minutes."""
    unit, before, after = f["unit"], f["before"], f["after"]
    if unit == "per 10 min" and f.get("minutes"):
        k = f["minutes"] / 10
        unit = f"in {f['minutes']} min"
        before, after = round(before * k, 2), round(after * k, 2 if f["metric"] == "xg" else 0)
    out = {
        "label": f["label"],
        "unit": unit,
        "team": f["team"],
        "before": before,
        "after": after,
        "effect_sd": f["effect_sd"],
        "source": f["agent"],
    }
    if f.get("player"):
        out["player"] = f["player"]
        out["name"] = f["name"]
    if f.get("replaced"):
        out["vs"] = f["replaced_name"]
        out["vs_label"] = "replaced player"
    return out


def fallback_stats(m: Moment, found: dict[str, list[Finding]]) -> list[Finding]:
    """A red card always gets a card; show how the 10 men are doing even if nothing moved much."""
    if not m.events or m.events[0].kind != "red_card":
        return []
    ten = [f for f in found["team_play"] if f["team"] == m.events[0].team_id and f["metric"] in ("possession", "passes")]
    return ten[:1]


def explain(md: MatchData, m: Moment) -> dict[str, Any]:
    clock = md.clock_of(m.now - 1)
    md = md.until(m.now)  # the agents only ever see the match as it stood at that minute
    found = investigate(md, m)
    cause, lead = decide_cause(md, m, found)
    stats = choose_stats(m, cause, found, lead)
    return assemble(md, m, clock, found, cause, stats)


def assemble(
    md: MatchData,
    m: Moment,
    clock: str,
    found: dict[str, list[Finding]],
    cause: dict[str, Any],
    stats: list[Finding],
    confidence_penalty: float = 0.0,
) -> dict[str, Any]:
    """The card for one moment, once the cause and stats are chosen (by this module or by agents)."""
    top = max((abs(s["effect_sd"]) for s in stats), default=0.0)
    confidence = round(max(0.05, min(0.95, 0.35 + 0.12 * top) - confidence_penalty), 2)
    salience = round(max(m.swing / SWING_FULL, top / 3), 2)
    return {
        "match_id": md.meta["match_id"],
        "at": m.now,
        "salience": salience,
        "show": m.shifted or top >= 2.5,
        "clock": clock,
        "mode": m.mode,
        "shifted": m.shifted,
        "anchor": {
            "label": anchor_label(md, m, cause),
            "m": m.anchor_m,
            "event_ids": [e.event_id for e in m.events if e.event_id],
        },
        "stats": [_stat_out(md, s) for s in stats],
        "momentum": {
            "home": md.teams[0],
            "away": md.teams[1],
            "before": round(m.momentum_before, 1),
            "now": round(m.momentum_now, 1),
            "gainer": m.gainer,
            "swing": round(m.swing, 1),
        },
        "cause": {**cause, "confidence": confidence},
        "story": match_story(stats),
        "text": compose(md, cause, stats, m.gainer),
        "findings": {k: v[:8] for k, v in found.items()},
    }


def explain_match(md: MatchData) -> dict[str, Any]:
    """Every card for a match, plus the momentum scale and the timeline."""
    from .watcher import momentum_series

    return {
        "match_id": md.meta["match_id"],
        "teams": [{"team_id": t["team_id"], "name": t["name"], "short_name": t.get("short_name")} for t in md.meta["teams"]],
        "momentum": momentum_series(md),
        "timeline": [
            {"kind": k.kind, "m": k.m, "clock": k.clock, "team": k.team_id, "name": md.names.get(k.player_id or "", "")}
            for k in md.key_events
        ],
        "cards": [explain(md, m) for m in watch(md)],
    }
