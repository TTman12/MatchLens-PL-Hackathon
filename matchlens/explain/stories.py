"""Play-style stories: pairs of stats that together say how a team's play changed, and the short
sentence that tells a fan what that means.

One number rarely explains a shift. Possession going up says nothing on its own; possession up
*and* more passes in their own half says a team is keeping the ball and playing it safe, which is
why the other side can't attack. A story is two stats that move together for one team, each in a
set direction.

Every card also gets a sentence, written three ways: for a neutral, for fans of each team. The
sentences are templates filled from the stats chosen, so they never claim more than the numbers on
the card show.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .match import MatchData
from .specialists import Finding


@dataclass(frozen=True)
class Story:
    key: str
    stats: tuple[tuple[str, int], tuple[str, int]]  # (metric, direction) for the team the story is about
    control: int  # +1: the story wins that team momentum; -1: it hands momentum to the other side
    neutral: str
    own: str  # for fans of the team the story is about
    other: str  # for fans of the other team


STORIES = [
    Story(
        "safe_possession",
        (("possession", +1), ("own_half_passes", +1)),
        +1,
        "{T} are keeping the ball in their own half and playing it safe.",
        "{T} are keeping the ball and playing it safe in their own half.",
        "{T} are keeping the ball deep and playing it safe.",
    ),
    Story(
        "sitting_deep",
        (("defending_height", -1), ("clearances", +1)),
        -1,
        "{T} are sitting deeper and clearing the ball more.",
        "{T} are defending much deeper and making more clearances.",
        "{T} are sitting deep and clearing the ball.",
    ),
    Story(
        "pushed_back",
        (("own_half_passes", +1), ("clearances", +1)),
        -1,
        "{T} are stuck passing in their own half and clearing their lines.",
        "{T} are stuck in their own half and clearing their lines.",
        "{T} are stuck in their own half and clearing it.",
    ),
    Story(
        "pushing_up",
        (("own_half_passes", -1), ("final_third_passes", +1)),
        +1,
        "{T} have pushed up: fewer passes in their own half, more in {O}'s final third.",
        "{T} have pushed up the pitch and are passing in {O}'s final third.",
        "{T} have pushed up and are passing in {O}'s final third.",
    ),
    Story(
        "high_press",
        (("high_turnovers", +1), ("defending_height", +1)),
        +1,
        "{T} are pressing higher up the pitch and winning the ball back near {O}'s goal.",
        "{T} are pressing higher and winning the ball back near goal.",
        "{T} are pressing high and winning the ball back near {O}'s goal.",
    ),
    Story(
        "pinned_back",
        (("final_third_passes", +1), ("box_entries", +1)),
        +1,
        "{T} are passing in {O}'s final third and getting into the box more often.",
        "{T} are camped in {O}'s half, passing around the box and getting into it.",
        "{T} are playing in {O}'s final third and getting into the box.",
    ),
    Story(
        "wing_play",
        (("crosses", +1), ("box_entries", +1)),
        +1,
        "{T} are attacking down the wings and crossing into the box more.",
        "{T} are going down the wings and getting crosses into the box.",
        "{T} are attacking down the wings and crossing into {O}'s box.",
    ),
    Story(
        "more_threat",
        (("shots", +1), ("xg", +1)),
        +1,
        "{T} are getting more shots away, and better ones.",
        "{T} are getting more shots away, and from better positions.",
        "{T} are getting more shots away, and better ones.",
    ),
    Story(
        "driving_forward",
        (("progressive_passes", +1), ("final_third_passes", +1)),
        +1,
        "{T} are moving the ball forward quicker and getting it into the final third.",
        "{T} are moving the ball forward quicker and getting it into the final third.",
        "{T} are moving the ball forward quicker and getting it into {O}'s final third.",
    ),
    Story(
        "taking_the_tempo",
        (("passes", +1), ("pass_accuracy", +1)),
        +1,
        "{T} are passing more, and more accurately: they've taken control of the tempo.",
        "{T} are passing more, and more accurately: they've taken control of the tempo.",
        "{T} are passing more, and more accurately.",
    ),
    Story(
        "winning_battles",
        (("duels_won", +1), ("duels", +1)),
        +1,
        "The game has got more physical and {T} are winning more of the battles.",
        "The game has got more physical and {T} are winning more of the battles.",
        "The game has got more physical and {T} are winning more of the battles.",
    ),
    Story(
        "going_long",
        (("long_balls", +1), ("pass_length", +1)),
        0,
        "{T} have started going long, skipping the midfield.",
        "{T} have started going long, skipping the midfield.",
        "{T} have started going long, skipping the midfield.",
    ),
    Story(
        "losing_grip",
        (("pass_accuracy", -1), ("possession", -1)),
        -1,
        "{T}'s passing has gone loose and they keep giving the ball away.",
        "{T}'s passing has gone loose and they keep giving the ball away.",
        "{T}'s passing has gone loose and they keep giving the ball away.",
    ),
]
BY_KEY = {s.key: s for s in STORIES}

# what a fan reads when a stat goes up or down, for cards no story fits
PHRASES: dict[str, tuple[str, str]] = {
    "possession": ("seeing more of the ball", "seeing less of the ball"),
    "pass_accuracy": ("passing more accurately", "giving the ball away more"),
    "final_third_passes": ("passing more in the final third", "passing less in the final third"),
    "progressive_passes": ("moving the ball forward more", "moving the ball forward less"),
    "box_entries": ("getting into the box more", "getting into the box less"),
    "shots": ("shooting more", "shooting less"),
    "xg": ("creating better chances", "creating less"),
    "defending_height": ("defending higher up the pitch", "defending deeper"),
    "ppda": ("pressing less", "pressing harder"),
    "high_turnovers": ("winning the ball back high up more", "winning the ball back high up less"),
    "duels_won": ("winning more of their duels", "losing more of their duels"),
    "long_balls": ("going long more", "playing it shorter"),
    "pass_length": ("playing longer passes", "playing shorter passes"),
    "passes": ("passing more", "passing less"),
    "own_half_passes": ("keeping the ball in their own half", "passing further up the pitch"),
    "clearances": ("clearing the ball more", "clearing the ball less"),
    "crosses": ("crossing more", "crossing less"),
    "duels": ("getting into more duels", "getting into fewer duels"),
    "fouls": ("fouling more", "fouling less"),
    "distance": ("running more", "running less"),
    "sprints": ("sprinting more", "sprinting less"),
    "field_tilt": ("playing more in the final third", "playing less in the final third"),
    "hsr": ("running harder", "running less hard"),
}
SHARES = {"possession", "field_tilt"}  # one side's share is the other's: never the whole story on its own
MIN_EACH = 1.0  # each stat in a story must move at least this much (random-window spreads)
MIN_TOP = 1.5  # and one of them clearly


def _visible(f: Finding) -> bool:
    if f["unit"] != "per 10 min" or not f.get("minutes"):
        return True
    return bool(abs(f["after"] - f["before"]) * f["minutes"] / 10 >= 2)


def aligned(story: Story, team: str, gainer: str | None) -> bool:
    if gainer is None or story.control == 0:
        return True
    return story.control * (1 if team == gainer else -1) > 0


def find_stories(team_play: list[Finding], gainer: str | None) -> list[dict[str, Any]]:
    """Every story the team-play findings support, best first. Each holds the two findings."""
    by = {(f["team"], f["metric"]): f for f in team_play}
    teams = sorted({f["team"] for f in team_play})
    out = []
    for s in STORIES:
        for t in teams:
            pair = [by.get((t, k)) for k, _ in s.stats]
            if any(f is None for f in pair):
                continue
            fs = [f for f in pair if f is not None]
            if not all(f["effect_sd"] * d >= MIN_EACH for f, (_, d) in zip(fs, s.stats, strict=True)):
                continue
            if max(abs(f["effect_sd"]) for f in fs) < MIN_TOP or not all(_visible(f) for f in fs):
                continue
            score = sum(min(abs(f["effect_sd"]), 4.0) for f in fs)
            out.append({"key": s.key, "team": t, "stats": fs, "score": round(score, 2), "aligned": aligned(s, t, gainer)})
    out.sort(key=lambda x: (not x["aligned"], -x["score"]))
    return out


def match_story(stats: list[Finding]) -> str | None:
    """The story two chosen findings tell, if they tell one."""
    if len(stats) != 2 or stats[0]["team"] != stats[1]["team"] or stats[0].get("player") or stats[1].get("player"):
        return None
    got = {(f["metric"], 1 if f["effect_sd"] > 0 else -1) for f in stats}
    return next((s.key for s in STORIES if set(s.stats) == got), None)


def _phrase(f: Finding) -> str:
    up, down = PHRASES.get(f["metric"], (f"seeing more {f['label'].lower()}", f"seeing less {f['label'].lower()}"))
    return up if f["after"] >= f["before"] else down


def _lower_first(s: str) -> str:
    """After a prefix: "Since scoring, the game has..." but "Since scoring, Ashmere are..."."""
    return "the" + s[3:] if s.startswith("The ") else s


def _fallback(md: MatchData, stats: list[Finding]) -> str:
    team_stats = [f for f in stats if not f.get("player")]
    if not team_stats:
        return ""
    a = team_stats[0]
    if len(team_stats) == 1:
        s = f"{md.short(a['team'])} are {_phrase(a)}."
    elif team_stats[1]["team"] == a["team"]:
        s = f"{md.short(a['team'])} are {_phrase(a)} and {_phrase(team_stats[1])}."
    else:
        b = team_stats[1]
        s = f"{md.short(a['team'])} are {_phrase(a)}, while {md.short(b['team'])} are {_phrase(b)}."
    return s


# a player doing more: what a fan reads
PLAYER_PHRASES = {
    "defensive_actions": "making more tackles",
    "duels_won": "winning more duels",
    "progressive_passes": "playing more passes forward",
    "sprints": "sprinting more",
    "distance_m": "covering more ground",
    "duels": "getting into more duels",
    "touches": "seeing more of the ball",
}


def _player_text(stats: list[Finding]) -> str:
    """ "Wexez is making more tackles and winning more duels." or two players, one clause each."""
    names: dict[str, list[str]] = {}
    for f in stats:
        names.setdefault(f["name"], []).append(PLAYER_PHRASES.get(f["metric"], f"doing more {f['label'].lower()}"))
    parts = [f"{n} is {' and '.join(p)}" for n, p in names.items()]
    return ", and ".join(parts) + "."


def _story_text(md: MatchData, key: str, team: str, view: str) -> str:
    s = BY_KEY[key]
    tpl = s.own if view == team else s.other if view == md.opp(team) else s.neutral
    return tpl.format(T=md.short(team), O=md.short(md.opp(team)))


def _sub_text(md: MatchData, f: Finding) -> str:
    more = f["after"] >= f["before"]
    if f["metric"] == "distance_m":
        what = "covering more ground" if more else "covering less ground"
        return f"{f['name']} is {what} than {f['replaced_name']} was."
    return f"{f['name']} is getting through {'more' if more else 'fewer'} {f['label'].lower()} than {f['replaced_name']} did."


# what led to the change: (when the sentence is about the same team, when it is about the other)
PREFIX = {
    "goal_lift": ("Since scoring, ", "Since {T} scored, "),
    "chasing_the_game": ("Since going behind, ", "Since {T} went behind, "),
    "recovery": ("Back from a dip, ", "With {T} back from a dip, "),
    "red_card_reshape": ("Down to ten men, ", "With {T} down to ten men, "),
}


def _prefixed(md: MatchData, kind: str, team: str | None, about: str, body: str) -> str:
    if kind not in PREFIX or not team:
        return body
    same, other = PREFIX[kind]
    return (same if about == team else other.format(T=md.short(team))) + _lower_first(body)


def compose(md: MatchData, cause: dict[str, Any], stats: list[Finding], gainer: str | None) -> dict[str, str]:
    """The card's sentence for a neutral and for fans of each team: {"neutral": ..., <team_id>: ...}."""
    kind = cause["kind"]
    team = cause.get("team")
    story = match_story(stats)
    out: dict[str, str] = {}
    for view in ("neutral", *md.teams):
        if kind == "red_card_holding":
            s = f"Down to ten men, {md.short(team or '')} are holding their shape so far."
        elif kind in ("goal_no_reaction", "half_time_no_change"):
            s = "The goal hasn't swung momentum." if kind == "goal_no_reaction" else "Half-time hasn't swung momentum."
            what = _fallback(md, stats)
            if what:
                s = f"{s[:-1]}: {what}"
        elif kind == "sub_no_change":
            s = "The change hasn't altered the pattern of play so far."
        elif kind == "fatigue" and team:
            s = f"{md.short(team)}'s starters are tiring: they're sprinting much less than earlier."
        elif kind == "substitution_impact":
            sub = next((f for f in stats if f.get("replaced")), None)
            s = _sub_text(md, sub) if sub else ""
            rest = [f for f in stats if f is not sub]
            if rest:
                s = (s + " " + _fallback(md, rest)).strip()
        elif any(f.get("claim") == "player_change" for f in stats):
            stars = [f for f in stats if f.get("claim") == "player_change"]
            body = " ".join(x for x in (_player_text(stars), _fallback(md, stats)) if x)
            s = _prefixed(md, kind, team, "", body)
        elif story is not None:
            s = _prefixed(md, kind, team, stats[0]["team"], _story_text(md, story, stats[0]["team"], view))
        elif stats:
            about = next((f["team"] for f in stats if not f.get("player")), stats[0]["team"])
            s = _prefixed(md, kind, team, about, _fallback(md, stats))
        elif gainer is not None:
            s = f"{md.short(gainer)} have taken over, though no single stat stands out yet."
        else:
            s = ""
        out[view] = s
    return out
