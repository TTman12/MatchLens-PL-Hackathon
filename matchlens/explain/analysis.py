"""MatchLens analysis: what a side could do about the momentum, as fans argue it with their mates.

After a card says what changed, a second card gives the debate: what the side that lost momentum
could do to win it back ("push the line back up"), or what the side that has it should keep doing.
Each idea is a lever, and a lever only comes up when a stat in the match backs it: a side is told to
push its line up only when its defending height has dropped, to stop going long only when its long
balls have gone up. The stat goes on the card under the idea, so the viewer sees why.

This is the deterministic analyst. The Analyst agent on Foundry (matchlens/agents/analyst.py) picks
from the same levers and writes its own lines, held to them by a check in code; these lines are its
offline stand-in and its fallback. Nothing here knows what a manager said or plans: the levers are
ways of playing the stats can see, never formations, instructions or personnel.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import spanish
from .specialists import Finding

FIX, KEEP = "fix", "keep"  # for the side that lost momentum; for the side that has it
STRONG = 1.5  # spreads a stat must have moved before it backs a lever
FAIR = 1.0  # good enough when nothing clears STRONG for a side: still a real, visible change
PER_TEAM = 3  # levers per club offered to the Analyst agent

# what a line talking about each topic sounds like; the Analyst's line must speak to its lever's topic
TOPICS = {
    "line": r"\b(defensive line|the line|their line|back line|high(er)? line|line high\w*|line up|squeez\w*|deep\w*)\b",
    "press": r"\bpress(es|ing|ed)?\b",
    "possession": r"\b(keep(ing)? (the ball|it)|possession|on the ball|ball back|chas\w+)\b",
    "passing": r"\b(simple\w*|short\w*|cheap\w*|settle\w*|calm\w*|careless\w*|giv\w+ (it|the ball) away)\b",
    "forward": r"\b(forward|final third|the box|up the pitch|own half|bodies|players)\b",
    "long": r"\b(long balls?|go(es|ing)? long|hit(ting)? it long|direct\w*|over the top)\b",
    "wide": r"\b(flanks?|wings?|wide|cross(es|ing)?)\b",
    "duels": r"\b(battles?|duels?|second balls?|physical\w*)\b",
}
# topics distinct enough that a line raising one its lever doesn't cover is suggesting something
# the stats didn't back
EXCLUSIVE = ("line", "press", "long", "wide")


@dataclass(frozen=True)
class Lever:
    key: str
    mode: str  # FIX or KEEP
    metrics: tuple[str, ...]  # team-play stats that can back it
    whose: str  # "own": the advised side's stat; "opp": the other side's
    direction: int  # the move in that stat that calls for the lever
    idea: str  # in plain words, for the agent
    topics: tuple[str, ...]
    neutral: str | dict[str, str]  # {T} is the advised side, {O} the other; per game state or one line
    fan: str | dict[str, str]  # for fans of {T}


LEVERS = [
    # for the side that lost momentum
    Lever(
        "higher_line",
        FIX,
        ("defending_height",),
        "own",
        -1,
        "push the defensive line back up; they have dropped deep",
        ("line",),
        "{T} have dropped too deep. Pushing the line back up would squeeze the space {O} are enjoying.",
        "{T} need to push the line back up and stop inviting {O} on.",
    ),
    Lever(
        "press_again",
        FIX,
        ("high_turnovers",),
        "own",
        -1,
        "press high again; they have stopped winning the ball high up",
        ("press",),
        "{T} have stopped winning the ball high. Pressing again would stop {O} building from the back.",
        "{T} have to start pressing again and stop letting {O} play out.",
    ),
    Lever(
        "keep_ball",
        FIX,
        ("possession",),
        "own",
        -1,
        "keep the ball for longer; they have lost possession",
        ("possession",),
        {
            "behind": "{T} can't chase the game without the ball. They need to keep it for longer.",
            "*": "{T} need to keep the ball for longer and make {O} do the chasing.",
        },
        "{T} have to get on the ball and make {O} chase for a change.",
    ),
    Lever(
        "settle",
        FIX,
        ("pass_accuracy",),
        "own",
        -1,
        "keep passing simple; they are giving the ball away",
        ("passing",),
        "{T} are giving the ball away too cheaply. Simpler, shorter passes would help them settle.",
        "{T} need to calm down on the ball and keep their passing simple.",
    ),
    Lever(
        "get_out",
        FIX,
        ("own_half_passes",),
        "own",
        +1,
        "move the ball forward quicker; they are stuck passing in their own half",
        ("forward",),
        "{T} are stuck passing in their own half. They need to get the ball forward quicker.",
        "{T} have to be braver and move it forward, out of their own half.",
    ),
    Lever(
        "through_the_middle",
        FIX,
        ("long_balls", "pass_length"),
        "own",
        +1,
        "stop going long and play through midfield; their long balls are up",
        ("long",),
        "{T} keep going long and giving it back. Playing through midfield would give them a foothold.",
        "{T} need to stop hitting it long and play through the middle.",
    ),
    Lever(
        "beat_the_press",
        FIX,
        ("high_turnovers",),
        "opp",
        +1,
        "move the ball quicker to play through the other side's press, which is winning it high",
        ("press",),
        "{O}'s press is forcing mistakes. {T} need to move the ball quicker to play through it.",
        "{T} have to move it quicker and play through {O}'s press.",
    ),
    Lever(
        "cover_the_flanks",
        FIX,
        ("crosses",),
        "opp",
        +1,
        "get more cover out wide; the other side is crossing more",
        ("wide",),
        "{O} are getting down the flanks too easily. {T} need more cover out wide.",
        "{T} have to shut down the wide areas before {O} get the crosses in.",
    ),
    Lever(
        "win_battles",
        FIX,
        ("duels_won",),
        "own",
        -1,
        "win the individual battles again; their duels won are down",
        ("duels",),
        "{T} are losing the individual battles. Winning those back has to come first.",
        "{T} need to win their duels and the second balls again.",
    ),
    Lever(
        "more_bodies",
        FIX,
        ("final_third_passes", "box_entries"),
        "own",
        -1,
        "commit more players forward; they have stopped getting into the final third",
        ("forward",),
        "{T} aren't getting into the final third. They need more bodies forward to trouble {O}.",
        "{T} have to get more players forward and test {O}.",
    ),
    # for the side that has momentum
    Lever(
        "keep_going_forward",
        KEEP,
        ("progressive_passes", "final_third_passes"),
        "own",
        +1,
        "keep moving the ball forward early; it is working",
        ("forward",),
        "Getting the ball forward early is working for {T}. More of the same keeps {O} pinned back.",
        "{T} should keep moving it forward early: {O} can't cope with it.",
    ),
    Lever(
        "keep_pressing",
        KEEP,
        ("high_turnovers",),
        "own",
        +1,
        "keep pressing high; it is winning the ball back",
        ("press",),
        "{T}'s pressing is winning the ball high. Keeping it up will stop {O} settling.",
        "{T} should keep pressing high and keep {O} penned in.",
    ),
    Lever(
        "keep_the_line_high",
        KEEP,
        ("defending_height",),
        "own",
        +1,
        "keep the defensive line high; it has squeezed the game into the other half",
        ("line",),
        "{T} have pushed their line up and squeezed the game into {O}'s half. Holding it there keeps the pressure on.",
        "{T} should keep the line high and keep squeezing {O}.",
    ),
    Lever(
        "keep_the_ball",
        KEEP,
        ("possession",),
        "own",
        +1,
        "keep the ball and make the other side chase",
        ("possession",),
        {
            "leading": "{T} can see this out by keeping the ball and making {O} chase.",
            "*": "{T} should keep the ball and make {O} do the chasing.",
        },
        {
            "leading": "Keep the ball, make {O} chase, and {T} can see this out.",
            "*": "{T} should keep the ball, move {O} around and wait for the gaps.",
        },
    ),
    Lever(
        "keep_going_wide",
        KEEP,
        ("crosses",),
        "own",
        +1,
        "keep attacking down the flanks; the crosses are coming",
        ("wide",),
        "{T} are getting joy down the flanks. More balls in from wide could break {O}.",
        "{T} should keep going down the wings: {O} can't deal with it.",
    ),
    Lever(
        "keep_getting_in",
        KEEP,
        ("box_entries", "shots", "xg"),
        "own",
        +1,
        "keep committing players into the box; they are getting in more",
        ("forward",),
        "{T} are getting into the box more and more. Keep committing players forward and {O} will be tested.",
        "{T} should keep getting bodies into the box: {O} are struggling to cope.",
    ),
    Lever(
        "keep_battling",
        KEEP,
        ("duels_won",),
        "own",
        +1,
        "keep winning the individual battles",
        ("duels",),
        "{T} are winning the battles. Keeping that up keeps {O} on the back foot.",
        "{T} should keep winning the battles and keep {O} on the back foot.",
    ),
    Lever(
        "keep_going_direct",
        KEEP,
        ("long_balls",),
        "own",
        +1,
        "keep going direct over the other side's midfield",
        ("long",),
        "Going direct is working for {T}. Balls over the top keep {O} turning.",
        "{T} should keep going long over {O}'s midfield.",
    ),
]
BY_KEY = {lv.key: lv for lv in LEVERS}


def sides(gainer: str | None, teams: tuple[str, str] | list[str], momentum_now: float) -> tuple[str, str]:
    """(the side with momentum, the side without). With no shift, the bar says who is on top."""
    home, away = teams
    g = gainer or (home if momentum_now >= 50 else away)
    return g, (away if g == home else home)


def _visible(f: Finding) -> bool:
    if f["unit"] != "per 10 min" or not f.get("minutes"):
        return True
    return bool(abs(f["after"] - f["before"]) * f["minutes"] / 10 >= 2)


def levers_for(
    team: str, mode: str, found: list[Finding], on_card: set[tuple[str, str]], least: float = STRONG
) -> list[tuple[Lever, Finding, float]]:
    """The levers a stat backs for one side, best backed first."""
    out = []
    for lv in LEVERS:
        if lv.mode != mode:
            continue
        whose = team if lv.whose == "own" else next((f["team"] for f in found if f["team"] != team), None)
        best: tuple[Finding, float] | None = None
        for f in found:
            if f["team"] != whose or f["metric"] not in lv.metrics or not _visible(f):
                continue
            score = f["effect_sd"] * lv.direction
            if score < least:
                continue
            if (f["team"], f["metric"]) in on_card:  # a stat the viewer has just seen says less
                score *= 0.75
            if best is None or score > best[1]:
                best = (f, score)
        if best:
            out.append((lv, *best))
    out.sort(key=lambda x: -x[2])
    return out


def options(
    found: dict[str, list[Finding]],
    gainer: str | None,
    teams: list[str],
    momentum_now: float,
    card_stats: list[Finding],
    stat_out: Callable[[Finding], dict[str, Any]],
) -> tuple[str, str, list[dict[str, Any]]]:
    """(side with momentum, side without, the menu of backed levers for both)."""
    g, lo = sides(gainer, teams, momentum_now)
    team_play = [f for f in found.get("team_play", []) if f.get("claim") == "team_change"]
    on_card = {(f["team"], f["metric"]) for f in card_stats if not f.get("player")}
    menu: list[dict[str, Any]] = []
    for team, mode in ((lo, FIX), (g, KEEP)):
        backed = levers_for(team, mode, team_play, on_card) or levers_for(team, mode, team_play, on_card, FAIR)
        for lv, f, _ in backed[:PER_TEAM]:
            ev = stat_out(f)
            menu.append(
                {
                    "id": f"A{len(menu) + 1}",
                    "team": team,
                    "mode": mode,
                    "lever": lv.key,
                    "idea": lv.idea,
                    "evidence": {
                        "team": ev["team"],
                        "metric": f["metric"],
                        "stat": ev["label"],
                        "unit": ev["unit"],
                        "before": ev["before"],
                        "after": ev["after"],
                        "change": "up" if ev["after"] >= ev["before"] else "down",
                    },
                }
            )
    return g, lo, menu


def facts(fx: dict[str, Any], g: str, lo: str, menu: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything the Analyst may use. `fx` is the card's facts block (insight.py)."""
    return {
        "minute": fx["minute"],
        "teams": fx["teams"],
        "momentum_with": g,
        "momentum_against": lo,
        "card_says": fx["what_changed"],
        "card_stats": fx["stats"],
        "options": menu,
    }


def default_picks(afx: dict[str, Any]) -> dict[str, str]:
    """The best-backed lever for each side that has one."""
    picks: dict[str, str] = {}
    for o in afx["options"]:
        picks.setdefault(o["team"], o["id"])
    return picks


def lenses(afx: dict[str, Any], picks: dict[str, str]) -> dict[str, str]:
    """Which club each viewer's line is about: a fan hears about their club; a neutral about the
    side that lost momentum (that's the debate), or the side that has it when nothing backs a fix."""
    out = {t: t for t in afx["teams"] if t in picks}
    for t in (afx["momentum_against"], afx["momentum_with"]):
        if t in picks:
            out["neutral"] = t
            break
    return out


def _pick(spec: str | dict[str, str], state: str) -> str:
    return spec if isinstance(spec, str) else spec.get(state, spec["*"])


def lines(afx: dict[str, Any], picks: dict[str, str] | None = None, lang: str = "en") -> dict[str, str]:
    """The deterministic analysis line for each viewer who has one, in English or Spanish ("es")."""
    picks = picks or default_picks(afx)
    by_id = {o["id"]: o for o in afx["options"]}
    teams = afx["teams"]
    out = {}
    for lens, team in lenses(afx, picks).items():
        lv = BY_KEY[by_id[picks[team]]["lever"]]
        other = next(t for t in teams if t != team)
        fill = {"T": teams[team]["name"], "O": teams[other]["name"]}
        out[lens] = lever_line(lv.key, lens == "neutral", teams[team]["state"], fill, lang)
    return out


def lever_line(key: str, neutral: bool, state: str, fill: dict[str, str], lang: str = "en") -> str:
    """One lever's line: for a neutral or for the advised club's fans, in the advised club's game state."""
    lv = BY_KEY[key]
    es = spanish.LEVERS[key] if lang == "es" else (lv.neutral, lv.fan)
    return _pick(es[0] if neutral else es[1], state).format(**fill)


def analyse(fx: dict[str, Any], menu_parts: tuple[str, str, list[dict[str, Any]]]) -> dict[str, Any]:
    """The analysis block for a card: the facts, the picks and the lines."""
    g, lo, menu = menu_parts
    afx = facts(fx, g, lo, menu)
    picks = default_picks(afx)
    return {"facts": afx, "picks": picks, "text": lines(afx, picks)}


def speaks_to(line: str, topic: str) -> bool:
    return re.search(TOPICS[topic], line, re.I) is not None
