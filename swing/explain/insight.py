"""From numbers to a reading of the game: what the stats on a card say is going on, for each fan.

The stats on a card say *what* changed: more passes in the final third, more box entries. A fan
wants to know what that means: a team has gone on the attack, and with the score as it is, they
are chasing an equaliser. This module infers that reading from the card's evidence and the game
state, and writes it three ways (for a neutral, and for fans of each club).

It is the deterministic interpreter: the Interpreter agent on Foundry (swing/agents) writes
its own lines from the same facts, and these lines are its offline stand-in and its fallback. The
reading never goes beyond the evidence: it names a style of play the stats show and the game state
the scoreboard shows, never an instruction, an injury or anything else the data can't see.
"""

from __future__ import annotations

from typing import Any

from . import spanish
from .match import MatchData
from .specialists import Finding
from .stories import compose, match_story

# play-style stories (stories.py) and what they mean
STORY_READING = {
    "pushing_up": "attacking",
    "pinned_back": "attacking",
    "driving_forward": "attacking",
    "wing_play": "attacking",
    "more_threat": "attacking",
    "high_press": "pressing",
    "sitting_deep": "under_pressure",
    "pushed_back": "under_pressure",
    "safe_possession": "control",
    "taking_the_tempo": "control",
    "going_long": "direct",
    "losing_grip": "losing_control",
    "winning_battles": "physical",
}

# a single stat and the direction it moved: what it means for the team it is about
METRIC_READING = {
    ("shots", 1): "attacking",
    ("xg", 1): "attacking",
    ("box_entries", 1): "attacking",
    ("final_third_passes", 1): "attacking",
    ("final_third_entries", 1): "attacking",
    ("progressive_passes", 1): "attacking",
    ("crosses", 1): "attacking",
    ("own_half_passes", -1): "attacking",
    ("field_tilt", 1): "attacking",
    ("high_turnovers", 1): "pressing",
    ("ppda", -1): "pressing",
    ("defending_height", 1): "pressing",
    ("defending_height", -1): "under_pressure",
    ("clearances", 1): "under_pressure",
    ("own_half_passes", 1): "under_pressure",
    ("field_tilt", -1): "under_pressure",
    ("possession", 1): "control",
    ("passes", 1): "control",
    ("pass_accuracy", 1): "control",
    ("long_balls", 1): "direct",
    ("pass_length", 1): "direct",
    ("pass_accuracy", -1): "losing_control",
    ("possession", -1): "losing_control",
    ("passes", -1): "losing_control",
    ("duels_won", 1): "physical",
    ("shots", -1): "blunted",
    ("xg", -1): "blunted",
    ("box_entries", -1): "blunted",
    ("final_third_passes", -1): "blunted",
}

# Lines per reading. {T} is the team the reading is about, {O} the other side, {P} the players named.
# Each lens is either one line, or one line per game state of {T} (leading, level, behind) with "*"
# as the default.
LINES: dict[str, dict[str, Any]] = {
    "attacking": {
        "neutral": {
            "behind": "{T} have gone on the attack, looking for a way back into the game.",
            "leading": "{T} aren't sitting on their lead: they're still going forward.",
            "*": "{T} have moved up a gear and are playing on the front foot.",
        },
        "own": {
            "behind": "{T} are piling forward and look the likelier side to score next.",
            "leading": "{T} are going for the kill.",
            "*": "{T} are on the front foot and getting closer to a goal.",
        },
        "other": {
            "behind": "{O} are having to defend as {T} throw everything forward.",
            "leading": "{O} can't get a foothold while {T} keep coming forward.",
            "*": "{O} are being pushed back and are struggling to get out.",
        },
    },
    "pressing": {
        "neutral": "{T} are hunting the ball high up the pitch and not letting {O} settle.",
        "own": "{T} are pressing hard and forcing mistakes from {O}.",
        "other": "{O} are being pressed into mistakes and can't play out from the back.",
    },
    "under_pressure": {
        "neutral": {
            "leading": "{T} have dropped deep to protect their lead.",
            "*": "{T} have been pushed back and are defending for long spells.",
        },
        "own": {
            "leading": "{T} are digging in to hold on to what they have.",
            "*": "{T} are under the cosh and need to find a way out of their own half.",
        },
        "other": {
            "leading": "{O} have {T} pinned back, but still have to find a way through.",
            "*": "{O} are camped in {T}'s half and asking the questions.",
        },
    },
    "control": {
        "neutral": {
            "leading": "{T} are keeping the ball and taking the sting out of the game.",
            "*": "{T} have taken control of the ball and are setting the tempo.",
        },
        "own": {
            "leading": "{T} are keeping the ball and managing the game.",
            "*": "{T} are running the game now, making {O} chase.",
        },
        "other": "{O} are chasing shadows while {T} keep the ball.",
    },
    "direct": {
        "neutral": "{T} have switched to a more direct game, going long to skip the midfield.",
        "own": "{T} are going direct to get the ball forward quicker.",
        "other": "{T} have given up building through midfield and are going long against {O}.",
    },
    "losing_control": {
        "neutral": "{T} have lost their grip on the game and keep giving the ball away.",
        "own": "{T} have gone loose on the ball and need to settle down.",
        "other": "{O} are feeding off {T}'s sloppy passing.",
    },
    "physical": {
        "neutral": "The game has turned into a battle, and {T} are winning it.",
        "own": "{T} are winning the physical battle.",
        "other": "{O} are being bullied off the ball by {T}.",
    },
    "blunted": {
        "neutral": "{T} have lost their cutting edge going forward.",
        "own": "{T} are finding it harder to create anything.",
        "other": "{O} have shut {T}'s attack down.",
    },
    "player_drive": {
        "neutral": "{P} {VERB} driving {T} on.",
        "own": "{P} {VERB} dragging {T} forward.",
        "other": "{P} {VERB} the problem for {O} right now.",
    },
    "fresh_legs": {
        "neutral": "{P} has brought fresh energy to {T}.",
        "own": "{P} has given {T} a lift off the bench.",
        "other": "{P} has made a difference for {T} since coming on.",
    },
    "sub_quiet": {
        "neutral": "{P} hasn't made the same impact since coming on.",
        "own": "{P} is still finding a way into the game.",
        "other": "{O} haven't been troubled by {T}'s change so far.",
    },
    "tiring": {
        "neutral": "{T} are tiring, and the game is opening up.",
        "own": "{T}'s legs are going and they need to hang on.",
        "other": "{O} can sense {T} are tiring.",
    },
    "ten_men": {
        "neutral": "Down to ten, {T} have had to reshape and sit in.",
        "own": "{T} are making the sacrifices to cope with ten men.",
        "other": "{O} have the extra man and {T} are having to dig in.",
    },
    "holding_shape": {
        "neutral": "Even with ten men, {T} are holding their shape.",
        "own": "{T} are coping well with ten men so far.",
        "other": "{O} haven't made the extra man count yet.",
    },
    "no_change": {
        "neutral": "Nothing has changed: the game is carrying on as it was.",
        "own": "It's business as usual for {T}.",
        "other": "It's business as usual for {O}.",
    },
    "taking_over": {
        "neutral": {
            "leading": "{T} are on top and in control of their lead.",
            "*": "{T} have got on top in this spell.",
        },
        "own": "{T} are on top and growing into the game.",
        "other": "{O} are on the back foot in this spell.",
    },
}

# A player's stat says what he is doing more of; these say how that moves the game: what it gives
# his club ({T}) and what it does to the other side ({O}). Used for player_drive and fresh_legs, in
# place of the generic lines above, when the card's player stat has an entry here.
PLAYER_LINES: dict[str, dict[str, str]] = {
    "sprints": {
        "neutral": "{P}'s running is stretching {O} and giving {T} more options going forward.",
        "own": "{P}'s aggressive running is giving {T} more attacking options and putting {O} under pressure.",
        "other": "{O} can't track {P}'s runs, and it's letting {T} pile on the pressure.",
    },
    "distance_m": {
        "neutral": "{P}'s work rate is giving {T} an extra body all over the pitch and closing down {O}'s space.",
        "own": "{P} is covering every blade of grass, so {T} are winning the race to every loose ball.",
        "other": "{P} is everywhere, and {O} are running out of space to play in.",
    },
    "progressive_passes": {
        "neutral": "{P}'s forward passing is breaking {O}'s lines and moving {T} up the pitch.",
        "own": "{P} is pulling the strings, breaking {O}'s lines and taking {T} up the pitch.",
        "other": "{P} keeps finding a way through {O}, and {T} are getting up the pitch because of it.",
    },
    "defensive_actions": {
        "neutral": "{P} keeps winning the ball back, so {T} get it again quickly and {O} can't build any rhythm.",
        "own": "{P} keeps breaking up {O}'s play, handing {T} the ball back again and again.",
        "other": "{P} keeps breaking up {O}'s moves before they get going, and {T} are taking over.",
    },
    "duels_won": {
        "neutral": "{P} is winning the battles, so {T} are keeping the ball and {O} are being pushed back.",
        "own": "{P} is winning every battle, and that's letting {T} take over from {O}.",
        "other": "{O} can't get the better of {P}, and every lost duel hands {T} the ball.",
    },
    "duels": {
        "neutral": "{P} is getting stuck in, adding bite to {T} and stopping {O} from playing.",
        "own": "{P} is getting stuck in and giving {T} an edge over {O}.",
        "other": "{P} is getting stuck in, and {O} aren't being given a moment on the ball.",
    },
    "touches": {
        "neutral": "{P} is on the ball far more, giving {T} an outlet and a way past {O}.",
        "own": "{P} is always available, giving {T} an outlet every time they win it.",
        "other": "{O} can't keep {P} quiet, and {T} are using the outlet.",
    },
}
# what a player stat going up does on the pitch, for the Interpreter agent
PLAYER_MEANING = {
    "sprints": "more runs: team mates get more options, and the other side has more ground to cover",
    "distance_m": "more ground covered: an extra body in attack and defence, less space for the other side",
    "progressive_passes": "more passes that move the ball well up the pitch, past the other side's lines",
    "defensive_actions": "more tackles, interceptions and blocks: the ball comes back sooner, the other side can't settle",
    "duels_won": "winning more one-on-one battles: his side keeps the ball, the other side loses it",
    "duels": "more one-on-one battles: a more physical, contested game around him",
    "touches": "on the ball more: his side has a reliable outlet",
}

READINGS = tuple(LINES)
NO_CHANGE = {
    "goal_no_reaction": "{T}'s goal hasn't changed the pattern of the game.",
    "sub_no_change": "{T}'s change hasn't altered the game so far.",
    "half_time_no_change": "{T} and {O} have picked up where they left off.",
}


def _state(goals: dict[str, int], team: str, other: str) -> str:
    return "leading" if goals[team] > goals[other] else "behind" if goals[team] < goals[other] else "level"


def _dir(f: dict[str, Any]) -> int:
    return 1 if f["after"] >= f["before"] else -1


def reading(cause: dict[str, Any], stats: list[Finding], gainer: str | None) -> tuple[str, str | None]:
    """(the reading, the team it is about) from what a card shows."""
    kind = cause["kind"]
    team = cause.get("team")
    if kind in ("goal_no_reaction", "sub_no_change", "half_time_no_change"):
        return "no_change", team or gainer
    if kind == "red_card_reshape":
        return "ten_men", team
    if kind == "red_card_holding":
        return "holding_shape", team
    if kind == "fatigue":
        return "tiring", team
    if kind == "substitution_impact":
        sub = next((f for f in stats if f.get("replaced")), None)
        return ("fresh_legs" if sub is None or _dir(sub) > 0 else "sub_quiet"), team
    if stats and any(f.get("claim") == "player_change" for f in stats):
        star = next(f for f in stats if f.get("claim") == "player_change")
        return "player_drive", star["team"]
    story = match_story(stats)
    if story:
        return STORY_READING[story], stats[0]["team"]
    for f in stats:
        key = (f["metric"], _dir(f))
        if not f.get("player") and key in METRIC_READING:
            return METRIC_READING[key], f["team"]
    return ("taking_over", gainer) if gainer else ("no_change", team)


def facts(
    md: MatchData, now: int, cause: dict[str, Any], stats: list[Finding], gainer: str | None, momentum: tuple[float, float]
) -> dict[str, Any]:
    """Everything the interpreter may use, in plain terms. Nothing else about the match is known."""
    home, away = md.teams
    goals = md.score_at(now)
    key, about = reading(cause, stats, gainer)
    return {
        "minute": md.clock_of(now - 1),
        "teams": {
            t: {"name": md.short(t), "side": side, "goals": goals[t], "state": _state(goals, t, md.opp(t))}
            for t, side in ((home, "home"), (away, "away"))
        },
        "gainer": gainer,
        "momentum_home_share": {"before": round(momentum[0]), "now": round(momentum[1])},
        "cause": cause["kind"],
        "story": match_story(stats),
        "what_changed": compose(md, cause, stats, gainer)["neutral"],
        "reading": {"key": key, "team": about},
        "stats": [
            {
                "team": f["team"],
                **({"player": f["name"]} if f.get("player") else {}),
                **({"replaced": f["replaced_name"]} if f.get("replaced") else {}),
                "stat": f["label"],
                "metric": f["metric"],
                **({"meaning": PLAYER_MEANING[f["metric"]]} if f.get("player") and f["metric"] in PLAYER_MEANING else {}),
                "before": f["before"],
                "after": f["after"],
                "change": "up" if f["after"] >= f["before"] else "down",
            }
            for f in stats
        ],
    }


def _pick(spec: Any, state: str) -> str:
    if isinstance(spec, str):
        return spec
    return str(spec.get(state, spec["*"]))


def lines(fx: dict[str, Any], lang: str = "en") -> dict[str, str]:
    """The deterministic reading, written for a neutral and for each club's fans, in English or
    Spanish ("es")."""
    es = lang == "es"
    teams = fx["teams"]
    ids = list(teams)
    key, t = fx["reading"]["key"], fx["reading"]["team"] or fx["gainer"] or ids[0]
    o = next(x for x in ids if x != t)
    players = list(dict.fromkeys(s["player"] for s in fx["stats"] if s.get("player")))
    if key == "fresh_legs" or key == "sub_quiet":
        players = players[:1]
    names = (" y " if es else " and ").join(players) or teams[t]["name"]
    verb = "are" if len(players) > 1 else "is"
    spec = dict((spanish.LINES if es else LINES)[key])
    star = next((s for s in fx["stats"] if s.get("player")), None)
    if key in ("player_drive", "fresh_legs") and star and star.get("metric") in PLAYER_LINES:
        # say how the player's contribution moves the game, not just what he is doing more of
        names, verb = star["player"], "is"
        spec = dict((spanish.PLAYER_LINES if es else PLAYER_LINES)[star["metric"]])
        if key == "fresh_legs":
            spec = {k: spanish.off_the_bench(v) if es else "Off the bench, " + v for k, v in spec.items()}
    if key == "no_change":
        spec["neutral"] = (spanish.NO_CHANGE if es else NO_CHANGE).get(fx["cause"], spec["neutral"])
    state = teams[t]["state"]
    fill = {"T": teams[t]["name"], "O": teams[o]["name"], "P": names, "VERB": spanish.VERB[verb] if es else verb}
    return {
        "neutral": _pick(spec["neutral"], state).format(**fill),
        t: _pick(spec["own"], state).format(**fill),
        o: _pick(spec["other"], state).format(**fill),
    }
