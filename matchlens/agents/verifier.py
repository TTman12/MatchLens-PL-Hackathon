"""What the Explainer may claim for a moment, and the Verifier that holds it to that.

The cause menu lists only causes the stats can back (see docs/explainer.md): the Explainer chooses
among them, it does not invent one. The Verifier then recomputes every number it picked from the
match tables and checks each pick against the screen rules. It is code, not a model, so it can't be
talked round.
"""

from __future__ import annotations

from typing import Any

from ..explain.explainer import STRONG, _partner, driver, fallback_stats
from ..explain.match import MatchData
from ..explain.specialists import Finding, investigate
from ..explain.stories import SHARES as LONE_SHARES
from ..explain.watcher import Moment
from .board import Board, eligible

Option = dict[str, Any]

MEANING = {
    "red_card_reshape": "the 10 men changed how they play (fewer passes, less of the ball, or a deeper line)",
    "red_card_holding": "the 10 men are holding their shape: little changed",
    "goal_lift": "the scorers kept pushing and took over",
    "chasing_the_game": "the team that conceded pushed to get back in it",
    "goal_no_reaction": "the goal changed nothing in the run of play",
    "substitution_impact": "this substitute is doing clearly more (or less) than the player he replaced",
    "sub_no_change": "the change made no visible difference",
    "half_time_no_change": "the second half started like the first ended",
    "fatigue": "this team's starters are running out of legs",
    "play_change": "the play itself changed (show what changed; no reason is claimed)",
    "recovery": "a team got back to its own level after a dip",
}


def cause_menu(md: MatchData, m: Moment, found: dict[str, list[Finding]]) -> list[Option]:
    """Every cause the evidence allows for this moment, as options C1, C2, ..."""
    lead = m.events[0] if m.events else None
    drv = driver(m, found["team_play"]) if m.gainer else None
    play: Option = {"kind": "play_change", "team": m.gainer, "driver": drv["family"] if drv else None}
    opts: list[Option] = []
    if lead is not None and lead.kind == "red_card":
        opts = [{"kind": "red_card_reshape", "team": lead.team_id}, {"kind": "red_card_holding", "team": lead.team_id}]
    elif lead is not None and lead.kind == "goal":
        if m.gainer is None:
            opts = [{"kind": "goal_no_reaction", "team": lead.team_id}]
        else:
            kind = "chasing_the_game" if m.gainer != lead.team_id else "goal_lift"
            opts = [{"kind": kind, "team": m.gainer, "driver": play["driver"]}]
    elif lead is not None and lead.kind == "substitution":
        for f in found["substitutions"]:
            if f["claim"] == "sub_vs_replaced" and abs(f["effect_sd"]) >= 2.5 and m.gainer in (None, f["team"]):
                opts.append({"kind": "substitution_impact", "team": f["team"], "player": f["player"], "name": f["name"]})
        opts.append(play if m.gainer else {"kind": "sub_no_change", "team": lead.team_id})
    elif lead is not None and lead.kind == "half_time":
        opts = [play if m.gainer else {"kind": "half_time_no_change", "team": None}]
    else:
        for f in found["players"]:
            if f["claim"] == "fatigue" and f["team"] != m.gainer:
                opts.append({"kind": "fatigue", "team": f["team"]})
        opts.append({**play, "kind": "recovery"} if m.mode == "recovery" else play)
    for i, o in enumerate(opts, 1):
        o["id"] = f"C{i}"
        o["meaning"] = MEANING[o["kind"]]
    return opts


def _key(f: Finding) -> tuple[Any, ...]:
    return (f["agent"], f["claim"], f["team"], f.get("player"), f.get("metric"))


class Verifier:
    """Checks a draft card (a cause option and up to two finding ids) for one moment."""

    def __init__(self, md: MatchData, m: Moment, board: Board, menu: list[Option]) -> None:
        self.md, self.m, self.board, self.menu = md, m, board, menu
        # recompute every specialist from the tables, independently of what was posted
        self._truth = {_key(f): f for fs in investigate(md, m).values() for f in fs}
        # a red card always gets a card, even when the 10 men's numbers barely moved
        self._fallback = [id(f) for f in fallback_stats(m, board.by_agent())]

    def check(self, cause_id: str, stat_ids: list[str]) -> list[str]:
        problems: list[str] = []
        cause = next((o for o in self.menu if o["id"] == cause_id), None)
        if cause is None:
            return [f"{cause_id} is not on the cause menu; choose one of {[o['id'] for o in self.menu]}"]
        if len(stat_ids) > 2:
            problems.append("at most two stats fit on a card")
        stats: list[Finding] = []
        for fid in stat_ids:
            f = self.board.findings.get(fid)
            if f is None:
                problems.append(f"{fid} is not on the board")
                continue
            if not eligible(f) and id(f) not in self._fallback:
                problems.append(f"{fid} can't go on screen (no clear change, too small to see, or not a stat)")
                continue
            ref = self._truth.get(_key(f))
            if ref is None or any(abs(float(ref[k]) - float(f[k])) > 0.011 for k in ("before", "after")):
                problems.append(f"{fid} does not match the tables when recomputed")
                continue
            stats.append(f)
        metrics = [f["metric"] for f in stats]
        if len(set(metrics)) < len(metrics):
            problems.append("two stats on the same metric")
        lone = len(stats) == 1 and stats[0]["metric"] in LONE_SHARES and not stats[0].get("player")
        if lone and _partner(self.m, self.board.by_agent(), stats) is not None:
            problems.append(
                f"{stats[0]['label']} on its own explains nothing: pair it with a stat that shows how the play changed"
            )
        for f in stats:
            if f["agent"] == "team_play":
                continue
            about_player = cause["kind"] == "substitution_impact" and f.get("player") == cause.get("player")
            about_fade = cause["kind"] == "fatigue" and f["claim"] == "fatigue" and f["team"] == cause["team"]
            if not (about_player or about_fade):
                problems.append(f"{fid_of(self.board, f)} is about a player, but the cause is not about that player")
        if cause["kind"] == "substitution_impact" and not any(f.get("player") == cause.get("player") for f in stats):
            problems.append("a substitution_impact card must show that substitute against the player he replaced")
        if cause["kind"] == "fatigue" and not any(f["claim"] == "fatigue" for f in stats):
            problems.append("a fatigue card must show the fade")
        if cause["kind"] == "red_card_reshape" and not any(
            f["team"] == cause["team"]
            and f["metric"] in ("passes", "defending_height", "possession")
            and f["effect_sd"] <= -STRONG * 0.75
            for f in stats
        ):
            problems.append(
                "red_card_reshape needs the 10 men's passes, possession or defending height clearly down; else red_card_holding"
            )
        if not stat_ids and any(
            f["agent"] == "team_play" and eligible(f) and abs(f["effect_sd"]) >= 1.5 for f in self.board.findings.values()
        ):
            problems.append("pick at least one stat: clear changes are on the board")
        return problems


def fid_of(board: Board, f: Finding) -> str:
    return board.id_of(f) or "?"
