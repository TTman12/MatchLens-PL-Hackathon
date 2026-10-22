"""The full-time recap: how the match went, as graphics a studio can put up at the final whistle.

The recap is mostly numbers and shapes, not prose:
- the result, and one headline per viewer (a neutral, and fans of each club);
- who had the game in each quarter-hour, from the momentum scale;
- the turning points: the cards on screen whose momentum swung most;
- a few full-time stat pairs, and the first-half and second-half split for analysts;
- one standout player per club, with the stat that sets them apart.

The headline comes from a pattern the numbers show (a comeback, a late winner, the better side
winning, winning against the run of play, a tight game, and three kinds of draw). This is the
deterministic recapper: the Recapper agent on Foundry (swing/agents/recapper.py) writes its own
headlines from the same facts, held to them by a check in code, and these are its fallback.
"""

from __future__ import annotations

import statistics as st
from typing import Any

from .match import MatchData

LATE = 80  # a goal from this broadcast minute on is a late one
CLEAR = 57  # average momentum share at which one side was clearly on top
AGAINST = 45  # a winner with less than this had less of the game

# pattern -> (neutral, the side the pattern is about, the other side), in English and Spanish.
# {W}/{L} are the winner and loser; in draws {X} is the side the pattern is about and {Y} the other.
HEADLINES: dict[str, dict[str, tuple[str, str, str]]] = {
    "en": {
        "comeback": (
            "{W} came from behind to beat {L}.",
            "{W} showed real character to come back and beat {L}.",
            "{L} let a lead slip against {W}.",
        ),
        "late_winner": (
            "{W} snatched it late against {L}.",
            "{W} found a late winner against {L}.",
            "{L} were undone late on by {W}.",
        ),
        "dominant": (
            "{W} were on top for most of the game and beat {L}.",
            "{W} were the better side and deserved to beat {L}.",
            "{L} were second best against {W} for long spells.",
        ),
        "against_the_run": (
            "{W} beat {L} despite having less of the game.",
            "{W} rode out the pressure and got the win against {L}.",
            "{L} had plenty of the game but lost to {W}.",
        ),
        "edged": (
            "{W} edged a tight game against {L}.",
            "{W} did enough to beat {L}.",
            "{L} came up just short against {W}.",
        ),
        "late_draw": (
            "{X} snatched a late draw against {Y}.",
            "{X} rescued a point late on against {Y}.",
            "{Y} were pegged back late on by {X}.",
        ),
        "draw_on_top": (
            "{X} had the better of it but couldn't beat {Y}.",
            "{X} did enough to win but had to settle for a draw with {Y}.",
            "{Y} held on for a draw against {X}.",
        ),
        "even_draw": (
            "{X} and {Y} couldn't be separated.",
            "{X} shared the points with {Y}.",
            "{Y} shared the points with {X}.",
        ),
    },
    "es": {
        "comeback": (
            "{W} remontó para ganar a {L}.",
            "{W} tuvo carácter para remontar y ganar a {L}.",
            "{L} dejó escapar su ventaja ante {W}.",
        ),
        "late_winner": (
            "{W} se lo llevó al final ante {L}.",
            "{W} encontró el gol de la victoria al final ante {L}.",
            "{L} cayó en los últimos minutos ante {W}.",
        ),
        "dominant": (
            "{W} mandó casi todo el partido y ganó a {L}.",
            "{W} fue mejor y mereció ganar a {L}.",
            "{L} fue inferior a {W} durante largos tramos.",
        ),
        "against_the_run": (
            "{W} ganó a {L} pese a tener menos el partido.",
            "{W} aguantó la presión y se llevó la victoria ante {L}.",
            "{L} tuvo mucho el partido pero perdió ante {W}.",
        ),
        "edged": (
            "{W} se llevó un partido igualado ante {L}.",
            "{W} hizo lo justo para ganar a {L}.",
            "{L} se quedó a las puertas ante {W}.",
        ),
        "late_draw": (
            "{X} arañó un empate al final ante {Y}.",
            "{X} rescató un punto al final ante {Y}.",
            "{Y} vio cómo {X} empataba al final.",
        ),
        "draw_on_top": (
            "{X} fue mejor pero no pudo ganar a {Y}.",
            "{X} hizo méritos para ganar, pero tuvo que conformarse con el empate ante {Y}.",
            "{Y} aguantó el empate ante {X}.",
        ),
        "even_draw": (
            "{X} y {Y} no pudieron desempatar.",
            "{X} repartió los puntos con {Y}.",
            "{Y} repartió los puntos con {X}.",
        ),
    },
}

# a turning point's short label, by play-style story or cause: (English, Spanish)
TURN_LABELS = {
    "safe_possession": ("Kept it safe", "Juego seguro"),
    "sitting_deep": ("Sat deep", "Repliegue"),
    "pushed_back": ("Pushed back", "Encerrado"),
    "pushing_up": ("Pushed up", "Adelanta líneas"),
    "high_press": ("High press", "Presión alta"),
    "pinned_back": ("Pinned them back", "Encierra al rival"),
    "wing_play": ("Went wide", "Juego por bandas"),
    "more_threat": ("More threat", "Más peligro"),
    "driving_forward": ("Drove forward", "Avanza líneas"),
    "taking_the_tempo": ("Took the tempo", "Marca el ritmo"),
    "winning_battles": ("Won the battles", "Gana los duelos"),
    "going_long": ("Went long", "Juego directo"),
    "losing_grip": ("Lost their grip", "Pierde el control"),
    "play_change": ("Took over", "Toma el mando"),
    "recovery": ("Hit back", "Reacciona"),
    "fatigue": ("Tiring", "Cansancio"),
    "substitution_impact": ("Sub's impact", "Impacto del cambio"),
    "sub_no_change": ("Change, no effect", "Cambio sin efecto"),
    "goal_no_reaction": ("No reaction", "Sin reacción"),
    "half_time_no_change": ("Same again", "Todo igual"),
    "chasing_the_game": ("Chasing the game", "A por el empate"),
    "goal_lift": ("Lifted by the goal", "Crecido tras el gol"),
    "red_card_reshape": ("Ten men", "Con diez"),
    "red_card_holding": ("Ten men holding", "Aguanta con diez"),
}

# full-time pairs for everyone, and the half-by-half split for analysts (keys of tables.TEAM_STATS)
FT_STATS = ("possession", "shots", "shots_on_target", "xg", "duels_won")
HALF_STATS = (
    "possession",
    "shots",
    "xg",
    "pass_accuracy",
    "progressive_passes",
    "final_third_entries",
    "duels_won",
    "high_turnovers",
)
# a standout's stat: player-table key, and how much a goal or an xG counts against the others
STAR_STATS = ("goals", "xg", "progressive_passes", "duels_won", "defensive_actions", "touches", "distance", "sprints")


def spells(md: MatchData, momentum: list[float], half_time_m: int) -> list[dict[str, Any]]:
    """The home side's average momentum share in each quarter-hour, on the broadcast clock."""
    n = md.last_minute + 1
    cuts = [0, 15, 30, half_time_m, half_time_m + 15, half_time_m + 30, n]
    names = ["0-15", "15-30", "30-HT", "HT-60", "60-75", "75-FT"]
    out = []
    for name, lo, hi in zip(names, cuts, cuts[1:], strict=False):
        part = momentum[lo:hi]
        if part:
            out.append({"label": name, "home": round(st.fmean(part))})
    return out


def turning_points(cards: list[dict[str, Any]], most: int = 3) -> list[dict[str, Any]]:
    """The on-screen cards whose momentum swung most, in time order."""
    ranked = sorted(cards, key=lambda c: -abs(c["momentum"]["now"] - c["momentum"]["before"]))[:most]
    out = []
    for c in sorted(ranked, key=lambda c: c["at"]):
        key = c.get("story") or c["cause"]
        en, es = TURN_LABELS.get(key, TURN_LABELS["play_change"])
        out.append(
            {
                "at": c["at"],
                "clock": c["clock"],
                "team": c["momentum"]["gainer"],
                "kind": c["kind"],
                "key": key,
                "cause": c["cause"],
                "label": {"en": en, "es": es},
                "before": round(c["momentum"]["before"]),
                "now": round(c["momentum"]["now"]),
            }
        )
    return out


def _goals(md: MatchData) -> list[tuple[int, str, str]]:
    """(m, clock, scoring team) for every goal."""
    return [(k.m, k.clock, k.team_id or "") for k in md.key_events if k.kind == "goal"]


def _minute(clock: str) -> int:
    base, _, extra = clock.rstrip("'").partition("+")
    return int(base) + (1 if extra else 0)


def pattern(md: MatchData, momentum: list[float]) -> dict[str, Any]:
    """The shape of the result: which headline fits, and the clubs it is about."""
    home, away = md.teams
    score = dict.fromkeys(md.teams, 0)
    trailed = dict.fromkeys(md.teams, False)
    lead_changes: list[tuple[int, str]] = []  # (broadcast minute, side that went ahead or levelled)
    for _, clock, team in _goals(md):
        score[team] += 1
        other = md.opp(team)
        trailed[other] = trailed[other] or score[other] < score[team]
        lead_changes.append((_minute(clock), team))
    final = [score[home], score[away]]
    share = {home: st.fmean(momentum) if momentum else 50.0}
    share[away] = 100 - share[home]
    if final[0] != final[1]:
        w = home if final[0] > final[1] else away
        lo = md.opp(w)
        # the goal that put the winner ahead for good
        tally = dict.fromkeys(md.teams, 0)
        decider = None
        for mm, team in lead_changes:
            tally[team] += 1
            if team == w and tally[w] == tally[lo] + 1:
                decider = mm
        if trailed[w]:
            kind = "comeback"
        elif decider is not None and decider >= LATE:
            kind = "late_winner"
        elif share[w] >= CLEAR:
            kind = "dominant"
        elif share[w] <= AGAINST:
            kind = "against_the_run"
        else:
            kind = "edged"
        return {"kind": kind, "winner": w, "loser": lo, "about": w, "other": lo, "score": final, "share": round(share[home])}
    last = lead_changes[-1] if lead_changes else None
    if last and last[0] >= LATE:
        x = last[1]
        kind = "late_draw"
    elif max(share.values()) >= CLEAR:
        x = max(share, key=lambda t: share[t])
        kind = "draw_on_top"
    else:
        x = home
        kind = "even_draw"
    return {
        "kind": kind,
        "winner": None,
        "loser": None,
        "about": x,
        "other": md.opp(x),
        "score": final,
        "share": round(share[home]),
    }


def headlines(md: MatchData, pat: dict[str, Any], lang: str = "en") -> dict[str, str]:
    """One headline for a neutral and for each club's fans."""
    neutral, about, other = HEADLINES[lang][pat["kind"]]
    a, o = pat["about"], pat["other"]
    fill = {"W": md.short(a), "L": md.short(o), "X": md.short(a), "Y": md.short(o)}
    return {"neutral": neutral.format(**fill), a: about.format(**fill), o: other.format(**fill)}


def _defs(stats: dict[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    return {d["key"]: d for d in stats[kind]}


def ft_pairs(stats: dict[str, Any], teams: list[str]) -> list[dict[str, Any]]:
    defs = _defs(stats, "team_stats")
    return [
        {"key": k, "label": defs[k]["label"], "unit": defs[k]["unit"], "values": [stats["teams"][t][k][-1] for t in teams]}
        for k in FT_STATS
    ]


def stars(stats: dict[str, Any], teams: list[str]) -> dict[str, dict[str, Any]]:
    """One standout per club: a scorer of two or more, else the player furthest above his team-mates
    on one stat (in spreads, over players who played at least an hour)."""
    defs = _defs(stats, "player_stats")
    out = {}
    for t in teams:
        squad = [p for p in stats["players"] if p["team"] == t and p["stats"]["minutes"][-1] >= 60 and p["role"] != "GK"]
        if not squad:
            continue
        best: tuple[float, dict[str, Any], str] | None = None
        for k in STAR_STATS:
            vals = [p["stats"][k][-1] for p in squad]
            sd = st.pstdev(vals) or 1.0
            mean = st.fmean(vals)
            for p, v in zip(squad, vals, strict=True):
                z = (v - mean) / sd + (10 if k == "goals" and v >= 2 else 0)
                if v > 0 and (best is None or z > best[0]):
                    best = (z, p, k)
        if best:
            _, p, k = best
            rank = 1 + sum(1 for q in squad if q["stats"][k][-1] > p["stats"][k][-1])
            out[t] = {
                "player": p["id"],
                "name": p["name"],
                "role": p["role"],
                "key": k,
                "label": defs[k]["label"],
                "unit": defs[k]["unit"],
                "value": p["stats"][k][-1],
                "rank": rank,
            }
    return out


def halves(md: MatchData, half_time_m: int, window: Any) -> list[dict[str, Any]]:
    """First half against second half for each club. `window(lo, hi)` gives team-table values."""
    first, second = window(0, half_time_m), window(half_time_m, md.last_minute + 1)
    return [{"key": k, "values": {t: [first[t][k], second[t][k]] for t in md.teams}} for k in HALF_STATS]


def recap(
    md: MatchData, momentum: list[float], half_time_m: int, cards: list[dict[str, Any]], stats: dict[str, Any], window: Any
) -> dict[str, Any]:
    """The full-time recap block of a bundle. `cards` are the bundle's on-screen cards."""
    pat = pattern(md, momentum)
    teams = md.teams
    defs = _defs(stats, "team_stats")
    split = halves(md, half_time_m, window)
    for row in split:
        row["label"], row["unit"] = defs[row["key"]]["label"], defs[row["key"]]["unit"]
    tps = turning_points(cards)
    return {
        "pattern": pat,
        "spells": spells(md, momentum, half_time_m),
        "turning_points": tps,
        "stats": ft_pairs(stats, teams),
        "halves": split,
        "stars": stars(stats, teams),
        "facts": facts(md, pat, tps),
        "text": headlines(md, pat),
    }


def facts(md: MatchData, pat: dict[str, Any], tps: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything the Recapper may use, in plain terms."""
    names = {t: md.short(t) for t in md.teams}
    return {
        "teams": {
            t: {"name": names[t], "side": side, "goals": pat["score"][i]}
            for i, (t, side) in enumerate(zip(md.teams, ("home", "away"), strict=True))
        },
        "result": "draw" if pat["winner"] is None else f"{names[pat['winner']]} won",
        "pattern": pat["kind"],
        "pattern_about": pat["about"],
        "home_momentum_share": pat["share"],
        "goals": [{"clock": c, "team": names[t]} for _, c, t in _goals(md)],
        "red_cards": [{"clock": k.clock, "team": names.get(k.team_id or "", "")} for k in md.key_events if k.kind == "red_card"],
        "turning_points": [
            {"clock": tp["clock"], "team": names.get(tp["team"] or "", ""), "what": tp["label"]["en"]} for tp in tps
        ],
    }
