"""Everything the broadcast screen needs for one match, as one JSON file.

The screen does no analysis: it plays a clock and shows what is in the bundle at each minute. The
bundle holds the momentum scale, the score and the timeline minute by minute, plus the cards the
Director put on screen, with their numbers already formatted.

    matchlens-broadcast out/matches/ash-brk-7 --out web/data      # one match folder
    matchlens-broadcast --demo 6 --out web/data                     # generate fresh demo matches
    matchlens-broadcast --demo 6 --out web/data --agents foundry    # explained by the agents on Foundry
    matchlens-broadcast --demo 6 --out web/data --enrich            # add the recap, follow-a-player, the
                                                                    # analyst detail and Spanish to the
                                                                    # bundles already there, keeping their cards

Each bundle also carries the full-time recap, follow-a-player, the analyst view's detail and the
Spanish screen (extras.py). With --agents, the Recapper writes the recap headlines and the
Translator the Spanish lines (--translator picks Azure AI Translator or the Foundry agent).
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from ..explain.analysis import lenses
from ..explain.director import direct
from ..explain.explainer import explain_match
from ..explain.match import MatchData, load
from . import extras
from .tables import stats_tables

MODE_TAG = {
    "red_card": "Red card",
    "goal": "Goal",
    "substitution": "Substitution",
    "half_time": "Half-time",
    "shift": "Momentum shift",
    "recovery": "Recovery",
}


def _num(v: float) -> str:
    if abs(v) >= 10 or float(v).is_integer():
        return f"{v:.0f}"
    return f"{v:.1f}" if abs(v) >= 1 else f"{v:.2f}".rstrip("0").rstrip(".")


def format_stat(md: MatchData, s: dict[str, Any]) -> dict[str, Any]:
    """value is the big number; usual is the comparison, written as a fan reads it."""
    unit = s["unit"]
    after, before = s["after"], s["before"]
    if unit.startswith("%"):
        value, usual = f"{after:.0f}%", f"{before:.0f}%"
        unit = unit[1:].strip()
    elif unit == "m":
        value, usual = f"{after:.0f}m", f"{before:.0f}m"
    elif unit.startswith("in "):
        value, usual = _num(after), _num(before)
    elif unit == "PPDA":
        value, usual = f"{after:.1f}", f"{before:.1f}"
    else:
        value, usual = _num(after), _num(before)
    team = s["team"]
    return {
        "label": s["label"],
        "team": team,
        "code": team.upper(),
        "player": s.get("name"),
        "value": value,
        "usual": usual,
        "usual_label": f"{s['vs']} (off)" if s.get("vs") else "before",
        "window": unit if unit.startswith("in ") else None,
        "unit": "" if unit in ("", "m") or unit.startswith("in ") else unit,
        "rise": after > before,
        **({"sd": s["effect_sd"]} if s.get("effect_sd") is not None else {}),
    }


def screen_analysis(md: MatchData, a: dict[str, Any] | None) -> dict[str, Any] | None:
    """The MatchLens analysis card for each viewer: whose club it is about, fix or keep, the line, and
    the stat behind it, formatted like the card's own stats."""
    if not a or not a["text"]:
        return None
    by_id = {o["id"]: o for o in a["facts"]["options"]}
    out = {}
    for lens, team in lenses(a["facts"], a["picks"]).items():
        o = by_id[a["picks"][team]]
        ev = o["evidence"]
        stat = format_stat(
            md, {"label": ev["stat"], "unit": ev["unit"], "team": ev["team"], "before": ev["before"], "after": ev["after"]}
        )
        out[lens] = {"team": team, "mode": o["mode"], "lever": o["lever"], "line": a["text"][lens], "stat": stat}
    return out


def card_kind(card: dict[str, Any]) -> str:
    events = card["anchor"]["event_ids"]
    if card["mode"] != "event":
        return str(card["mode"])
    label = card["anchor"]["label"]
    if label == "Since half-time":
        return "half_time"
    if label.endswith("red card"):
        return "red_card"
    if " goal " in label:
        return "goal"
    return "substitution" if events else "shift"


def under_the_hood(card: dict[str, Any]) -> dict[str, Any] | None:
    """What the agents did for this card, for the screen's under-the-hood drawer."""
    a = card.get("agents")
    if not a:
        return None
    specialists = []
    for t in a["trace"]:
        if t["agent"] in ("explainer", "verifier"):
            continue
        specialists.append({"agent": t["agent"], "status": t["status"], "verdict": t.get("verdict"), "note": t.get("note", "")})
    order = ["team_play", "players", "substitutions", "match_events"]
    specialists.sort(key=lambda s: order.index(s["agent"]) if s["agent"] in order else len(order))
    rounds = [t for t in a["trace"] if t["agent"] == "verifier"]
    return {
        "runner": a["runner"],
        "specialists": specialists,
        "board": a["board"],
        "why": a["why"],
        "verifier": [{"round": t["round"], "status": t["status"], "problems": t["problems"]} for t in rounds],
        "fallback": a["fallback"],
        "interpreter": a.get("interpreter"),
        "analyst": a.get("analyst"),
        "missing": a["missing"],
        "confidence": card["cause"]["confidence"],
    }


def build(md: MatchData, result: dict[str, Any] | None = None) -> dict[str, Any]:
    """The bundle for one match. `result` is an explained match (by default, the deterministic one)."""
    result = result or explain_match(md)
    shown = direct(result["cards"])
    home, away = md.teams
    score: list[list[int]] = []
    for m in range(md.last_minute + 1):
        s = md.score_at(m + 1) if m + 1 <= md.last_minute else md.score_at(md.last_minute)
        score.append([s[home], s[away]])
    if md.last_minute >= 0:  # goals in the final minute
        final = md.meta.get("final_score")
        if final:
            score[-1] = list(final)
    teams = []
    for t in md.meta["teams"]:
        teams.append(
            {
                "team_id": t["team_id"],
                "code": t["team_id"].upper(),
                "name": t["name"],
                "short_name": t.get("short_name") or t["name"],
                "colours": t.get("colours", {}),
            }
        )
    cards = []
    for c in shown:
        kind = card_kind(c)
        cards.append(
            {
                "at": c["at"],
                "clock": c["clock"],
                "kind": kind,
                "tag": MODE_TAG[kind],
                "anchor": c["anchor"]["label"],
                "anchor_m": c["anchor"]["m"],
                "stats": [format_stat(md, s) for s in c["stats"]],
                "momentum": {"before": c["momentum"]["before"], "now": c["momentum"]["now"], "gainer": c["momentum"]["gainer"]},
                "cause": c["cause"]["kind"],
                "story": c.get("story"),
                "text": c.get("text", {}),
                "analysis": screen_analysis(md, c.get("analysis")),
                "shifted": c["shifted"],
                "hood": under_the_hood(c),
            }
        )
    b = {
        "match_id": md.meta["match_id"],
        "venue": md.meta.get("venue"),
        "competition": md.meta.get("competition"),
        "synthetic": md.meta.get("synthetic", False),
        "physical_note": md.meta.get("physical_note"),
        "teams": teams,
        "minutes": md.last_minute + 1,
        "half_time_m": next((k.m for k in md.key_events if k.kind == "half_time"), 46),
        "clock": [md.clock_of(m) for m in range(md.last_minute + 1)],
        "momentum": result["momentum"],
        "score": score,
        "timeline": [
            {
                "kind": k.kind,
                "m": k.m,
                "clock": k.clock,
                "team": k.team_id,
                "player": md.names.get(k.player_id or "", ""),
                "player_off": md.names.get(k.player_off_id or "", ""),
            }
            for k in md.key_events
        ],
        "cards": cards,
        "candidates": len(result["cards"]),
        "stats": stats_tables(md),
        "agents": result.get("agents"),
    }
    return extras.add(md, b, shown)


def explain_with_agents(mds: list[MatchData], runner_name: str) -> list[dict[str, Any]]:
    """Explain every match with the agent crew, sharing one runner (and one set of Foundry agents)."""
    import asyncio

    from ..agents.analyst import analyse_cards
    from ..agents.crew import explain_match_async
    from ..agents.interpreter import interpret_cards
    from ..agents.runners import make_runner

    async def one(runner: Any, md: MatchData) -> dict[str, Any]:
        result = await explain_match_async(md, runner)
        shown = direct(result["cards"])  # only the cards that go on screen
        await asyncio.gather(interpret_cards(runner, md, shown), analyse_cards(runner, md, shown))
        result["agents"]["usage"] = runner.usage.as_dict()
        if getattr(runner, "safety", None) is not None:
            result["agents"]["content_safety"] = runner.safety.count.as_dict()
        return result

    async def go() -> list[dict[str, Any]]:
        runner = make_runner(runner_name)
        try:
            return list(await asyncio.gather(*(one(runner, md) for md in mds)))
        finally:
            await runner.close()

    return asyncio.run(go())


def finish(bundles: list[dict[str, Any]], agents: str | None, translator: str = "auto") -> None:
    """The steps after the cards, in place: the Recapper's headlines (with --agents) and the Spanish
    lines from the translator, each checked in code with the rules as the fallback."""
    import asyncio

    from ..agents.recapper import recap_bundle
    from ..agents.runners import make_runner
    from ..agents.translator import make_backend, translate_bundle

    async def go() -> None:
        runner = make_runner(agents) if agents else None
        try:
            backend = make_backend(translator, runner)
            if runner is not None:
                await asyncio.gather(*(recap_bundle(runner, b) for b in bundles))
            await asyncio.gather(*(translate_bundle(backend, b) for b in bundles))
            if runner is not None:
                for b in bundles:
                    b["recap"]["agents"]["usage"] = runner.usage.as_dict()
        finally:
            if runner is not None:
                await runner.close()

    asyncio.run(go())


def enriched(md: MatchData, b: dict[str, Any]) -> dict[str, Any]:
    """An existing bundle with the extras added, its cards (and their agents' lines) kept. The rules'
    Spanish line for each card is read from the card's own cause and stats."""
    return extras.add(md, b, [{"at": c["at"], "facts": extras.card_facts(md, c)} for c in b["cards"]])


def write_bundles(
    folders: list[Path], out: Path, agents: str | None = None, enrich: bool = False, translator: str = "auto"
) -> list[dict[str, Any]]:
    out.mkdir(parents=True, exist_ok=True)
    index = []
    mds = [load(f) for f in folders]
    if enrich:
        bundles = [enriched(md, json.loads((out / f"{md.meta['match_id']}.json").read_text())) for md in mds]
    else:
        results: list[dict[str, Any] | None] = list(explain_with_agents(mds, agents)) if agents else [None] * len(mds)
        bundles = [build(md, result) for md, result in zip(mds, results, strict=True)]
    finish(bundles, agents, translator)
    for b in bundles:
        (out / f"{b['match_id']}.json").write_text(json.dumps(b, separators=(",", ":"), ensure_ascii=False))
        h, a = b["teams"]
        index.append(
            {
                "match_id": b["match_id"],
                "home": h["short_name"],
                "away": a["short_name"],
                "score": b["score"][-1],
                "cards": len(b["cards"]),
                # the user screen's club picker shows every club in the index, not just this match's
                "teams": [{k: t[k] for k in ("team_id", "code", "short_name", "colours")} for t in (h, a)],
            }
        )
    (out / "index.json").write_text(json.dumps(index, indent=1) + "\n")
    return index


DEMO_FIXTURES = [("ash", "brk"), ("cal", "dun"), ("brk", "cal"), ("dun", "ash"), ("ash", "cal"), ("brk", "dun")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", type=Path, nargs="*", help="match folders in the public format")
    ap.add_argument("--demo", type=int, help="generate this many fresh demo matches instead")
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--out", type=Path, default=Path("web/data"))
    ap.add_argument("--agents", choices=["offline", "foundry"], help="explain with the agent crew on this runner")
    ap.add_argument("--enrich", action="store_true", help="keep the bundles in --out and add the extras to them")
    ap.add_argument(
        "--translator",
        choices=["auto", "azure", "agent", "offline"],
        default="auto",
        help="Spanish lines: Azure AI Translator, the Translator agent on the --agents runner, or the rules "
        "(auto: Azure when AZURE_TRANSLATOR_KEY is set, else the agent on Foundry, else the rules)",
    )
    args = ap.parse_args()
    if args.demo:
        from ..gen import generate_match
        from ..gen.cli import write_one

        with tempfile.TemporaryDirectory() as tmp:
            folders = []
            for i in range(args.demo):
                h, a = DEMO_FIXTURES[i % len(DEMO_FIXTURES)]
                m = generate_match(h, a, args.seed + i)
                folders.append(
                    write_one(
                        Path(tmp),
                        m.match_id,
                        m.home,
                        m.away,
                        m.seed,
                        m.events,
                        m.physical.rows,
                        m.manager.decisions,
                        m.manager.minutes,
                    )
                )
            index = write_bundles(folders, args.out, args.agents, args.enrich, args.translator)
    else:
        index = write_bundles(args.folders, args.out, args.agents, args.enrich, args.translator)
    for r in index:
        print(f"{r['match_id']:>20}  {r['home']} {r['score'][0]}-{r['score'][1]} {r['away']}  {r['cards']} cards")


if __name__ == "__main__":
    main()
