"""Half-time and full-time briefs from the Pundit, with replay timestamps.

At each ``period_end`` event the Pundit writes a short brief: the score, and the
biggest moment of the half with how far it moved the win probability. The brief cue
carries that moment's replay window, so the player can jump straight to it. Numbers
are checked against the brief's own evidence exactly like a fact box.
"""

from __future__ import annotations

import json
from typing import Any

from matchlens.contracts import ClaimType, Layer, MatchEvent, MomentType, Template

from .evidence import EvidenceLedger, fmt, pct
from .lenses import AgentCaller, parse_json, prompt
from .numbers import unsupported
from .providers import AgentTask, ProviderError
from .state import MomentContext, TemplateRef
from .templates import STRINGS, render

BRIEF_STRINGS = {
    "en": {
        "h.half_time": "Half-time: {home} {score_home}-{score_away} {away}",
        "h.full_time": "Full time: {home} {score_home}-{score_away} {away}",
        "s.biggest": "The biggest moment: {what}, which moved {team}'s win chance from "
        "{before}% to {after}%.",
        "s.quiet": "No moment has moved the win chance yet.",
        "w.goal": "{name}'s goal",
        "w.card": "{name}'s red card",
        "w.big_save": "{name}'s save",
        "w.big_chance": "{name}'s miss",
        "w.swing": "the swing in momentum",
    },
    "es": {
        "h.half_time": "Descanso: {home} {score_home}-{score_away} {away}",
        "h.full_time": "Final: {home} {score_home}-{score_away} {away}",
        "s.biggest": "El momento clave: {what}, que llevó la probabilidad de victoria de "
        "{team} del {before}% al {after}%.",
        "s.quiet": "Ningún momento ha movido aún la probabilidad de victoria.",
        "w.goal": "el gol de {name}",
        "w.card": "la roja a {name}",
        "w.big_save": "la parada de {name}",
        "w.big_chance": "la ocasión fallada por {name}",
        "w.swing": "el cambio de inercia",
    },
}
for _lang, _strings in BRIEF_STRINGS.items():
    STRINGS[_lang].update(_strings)


def _what_key(ctx: MomentContext) -> tuple[str, str]:
    m = ctx.moment
    if m.type is MomentType.GOAL:
        return "w.goal", str(ctx.facts.get("scorer", ""))
    if m.type is MomentType.CARD:
        return "w.card", str(ctx.facts.get("booked", ""))
    roles = {"big_save": "keeper", "big_chance": "shooter"}
    who = next((c.player_id for c in ctx.contributors if c.role == roles.get(str(m.type))), "")
    return f"w.{m.type}" if str(m.type) in roles else "w.swing", who


async def write_brief(
    caller: AgentCaller,
    end: MatchEvent,
    moments: list[MomentContext],
    names: dict[str, str],
    home_id: str,
    away_id: str,
    score: tuple[int, int],
) -> dict[str, Any] | None:
    """The brief cue for the period that ``end`` closes, or None if it cannot be verified."""
    ledger = EvidenceLedger()
    match_id = end.match_id
    params = {
        "home": names[home_id],
        "away": names[away_id],
        "score_home": str(score[0]),
        "score_away": str(score[1]),
    }
    ids = [
        ledger.add(
            ClaimType.STAT,
            f"{names[home_id]} {score[0]}-{score[1]} {names[away_id]}",
            end.event_id,
            {"score_home": score[0], "score_away": score[1]},
        )
    ]
    in_period = [c for c in moments if c.moment.period == end.period and c.surprise > 0]
    parts: list[str] = []
    camera = None
    if in_period:
        top = max(in_period, key=lambda c: (c.surprise, c.moment.importance))
        m = top.moment
        team = home_id if m.swing > 0 else away_id
        before = m.win_prob_before.home if team == home_id else m.win_prob_before.away
        after = m.win_prob_after.home if team == home_id else m.win_prob_after.away
        ids.append(
            ledger.add(
                ClaimType.WIN_PROB,
                f"{names[team]} win probability {pct(before)}% to {pct(after)}%",
                f"winprob:{match_id}:{fmt(m.t_peak)}",
                {"before": before, "after": after},
            )
        )
        what, who = _what_key(top)
        params |= {
            "team": names[team],
            "before": pct(before),
            "after": pct(after),
            "name": names.get(who, who),
            "what_key": what,
        }
        parts.append("s.biggest")
        camera = {"shot": "tactical_high", "replay": list(m.replay_window), "replay_speed": 0.5}
    else:
        parts.append("s.quiet")
    key = "h.half_time" if end.period == 1 else "h.full_time"
    ref = TemplateRef(key, params, parts, ids)
    headline, body = render(ref, "en")

    # Give the Pundit model the chance to write it; keep the template if it cannot verify.
    task = AgentTask(
        agent="pundit",
        instance="pundit-agent:brief",
        tier="strong",
        instructions=prompt("pundit"),
        prompt=json.dumps(
            {
                "lens": "pundit",
                "brief": "half-time" if end.period == 1 else "full-time",
                "draft": {"headline": headline, "body": body},
                "evidence": [
                    {"id": i.id, "fact": i.value, "numbers": i.numbers} for i in ledger.items
                ],
            }
        ),
        payload={"template": ref},
    )
    try:
        data = parse_json(await caller.provider.complete(task))
        h, b = str(data.get("headline", "")), str(data.get("body", ""))
        if h and len(h) <= 80 and len(b) <= 280 and not unsupported(f"{h} {b}", ledger.items):
            headline, body = h, b
            caller.trace.add(None, "pundit", task.instance, "brief", "ok", headline)
        else:
            caller.trace.add(
                None,
                "pundit",
                task.instance,
                "brief",
                "fallback",
                "model brief failed the evidence check; template used",
            )
    except (ProviderError, TimeoutError) as exc:
        caller.trace.add(None, "pundit", task.instance, "brief", "fallback", str(exc))

    cue: dict[str, Any] = {
        "match_id": match_id,
        "moment_id": None,
        "t_show": round(end.t + 5.0, 1),
        "duration": 20.0,
        "layer": Layer.PUNDIT,
        "template": Template.BRIEF,
        "lang": "en",
        "priority": 1.0,
        "_template": ref,
        "box": {
            "headline": headline,
            "body": body,
            "evidence": [i.model_dump(mode="json") for i in ledger.items],
        },
    }
    if camera:
        cue["camera"] = camera
    return cue
