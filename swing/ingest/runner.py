"""The minute-by-minute runner: a live match, explained as it is played.

Each minute the feed sends goes through the same chain as a recorded match, but one minute at a
time and with nothing from later in the match:

1. the adapter adds the minute to the match (feed.LiveMatch),
2. the Watcher checks whether something now needs explaining (explain.watcher.Watcher.step),
3. each new moment goes to the explainer: the agent crew, or the deterministic rules,
4. the Director decides on the spot which cards go on screen (explain.director.Director), and
5. the cards that go up get their on-screen lines (Interpreter and Analyst agents) when the crew runs.

    swing-feed run feed/ --runner offline            # agents with the deterministic rules as their brain
    swing-feed run feed/ --runner foundry --pace 2   # the agents on Microsoft Foundry, a minute every 2 s
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ..explain.director import Director
from ..explain.explainer import explain
from ..explain.match import MatchData
from ..explain.watcher import Moment, Watcher, momentum_series
from .feed import LiveMatch, Minute

Explain = Callable[[MatchData, Moment], Awaitable[dict[str, Any]]]
Finish = Callable[[MatchData, list[dict[str, Any]]], Awaitable[None]]


async def rules(md: MatchData, m: Moment) -> dict[str, Any]:
    """The deterministic Explainer, as a live explainer."""
    return explain(md, m)


class LiveRunner:
    """Feed it minutes with `add`; it returns the cards that go on screen in that minute."""

    def __init__(self, meta: dict[str, Any], explainer: Explain = rules, finish: Finish | None = None) -> None:
        self.match = LiveMatch(meta)
        self.watcher = Watcher()
        self.director = Director()
        self.explainer = explainer
        self.finish = finish
        self.moments: list[Moment] = []
        self.cards: list[dict[str, Any]] = []  # every candidate, in the order it was made

    async def add(self, minute: Minute) -> list[dict[str, Any]]:
        self.match.add(minute)
        md = self.match.md
        now = md.last_minute + 1  # everything before `now` is in
        moments = self.watcher.step(md, now)
        cards = list(await asyncio.gather(*(self.explainer(md, m) for m in moments)))
        self.moments += moments
        self.cards += cards
        shown = self.director.offer(cards)
        if shown and self.finish:
            await self.finish(md, shown)
        return shown

    @property
    def shown(self) -> list[dict[str, Any]]:
        return self.director.shown

    def result(self) -> dict[str, Any]:
        """The match so far, in the shape explain.explainer.explain_match returns."""
        md = self.match.md
        return {
            "match_id": md.meta["match_id"],
            "teams": [{"team_id": t["team_id"], "name": t["name"], "short_name": t.get("short_name")} for t in md.meta["teams"]],
            "momentum": momentum_series(md),
            "timeline": [
                {"kind": k.kind, "m": k.m, "clock": k.clock, "team": k.team_id, "name": md.names.get(k.player_id or "", "")}
                for k in md.key_events
            ],
            "cards": self.cards,
        }


def crew(runner: Any) -> tuple[Explain, Finish]:
    """The agent crew on `runner` (offline or Foundry) as a live explainer, plus the on-screen writers."""
    from ..agents.analyst import analyse_cards
    from ..agents.crew import explain_moment
    from ..agents.interpreter import interpret_cards

    async def explainer(md: MatchData, m: Moment) -> dict[str, Any]:
        return await explain_moment(runner, md, m)

    async def finish(md: MatchData, shown: list[dict[str, Any]]) -> None:
        await asyncio.gather(interpret_cards(runner, md, shown), analyse_cards(runner, md, shown))

    return explainer, finish


async def play(
    meta: dict[str, Any],
    minutes: list[Minute],
    explainer: Explain = rules,
    finish: Finish | None = None,
    pace: float = 0.0,
    on_card: Callable[[MatchData, dict[str, Any]], None] | None = None,
) -> LiveRunner:
    """Play a whole feed through a LiveRunner, a minute every `pace` seconds."""
    live = LiveRunner(meta, explainer, finish)
    for minute in minutes:
        for card in await live.add(minute):
            if on_card:
                on_card(live.match.md, card)
        if pace:
            await asyncio.sleep(pace)
    return live
