"""One "Generate match" press: a brand-new match, played through the agents as an unseen match.

1. The generator makes a match nobody has seen: a fresh random seed and a random pairing of the
   league's fictional clubs.
2. It is written as a provider's live feed (matchlens/ingest/feed.py): per-minute club and player
   tables plus key events, with no final score, no seed and no hidden truth. The generator's
   folder, truth file included, is deleted before the first minute is sent.
3. The feed goes into the minute-by-minute runner (matchlens/ingest/runner.py) a minute at a time.
   The Watcher, the specialists, the Explainer, the Director, the Interpreter and the Analyst only
   ever see the minutes that have arrived.
4. After each minute the screen's bundle is rebuilt from the match so far, so viewers can watch
   the cards arrive as the match plays.

The agents run on Microsoft Foundry when the daily budget allows and Foundry answers. An agent
that fails is retried, then a rules stand-in takes its task and the chain carries on, with the
incident logged on the card (failover.py; the admin screen's fault drill makes this happen on
purpose). If a moment takes too long, Foundry can't be reached, or the budget runs out mid-match,
that card and the rest of the match are written by the deterministic rules instead, and labelled so
on screen.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import random
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agents.runners import OfflineRunner, Runner
from ..broadcast.bundle import build
from ..explain.match import MatchData
from ..explain.watcher import Moment
from ..ingest.feed import Feed, export_feed, load_mapping, read_feed
from ..ingest.runner import LiveRunner
from .failover import Drill, FailoverRunner, recording
from .limits import DailyBudget

log = logging.getLogger(__name__)

PACE = 0.5  # seconds between feed minutes: ahead of the screen's 1.6 s a minute at 1x
MOMENT_TIMEOUT = 45.0  # seconds the crew gets for one moment before the rules take it
FINISH_TIMEOUT = 45.0  # for the Interpreter and Analyst on the cards going up
RECAP_TIMEOUT = 60.0  # for the Recapper and the Translator at full time
SPAN = 98  # minutes the timeline spans until the real length is known at full time
REBUILD = 1.0  # seconds between bundle rebuilds (a card or full time rebuilds at once)
SEEDS = (100_000, 999_999)  # clear of the demo (31-36), tuning (2026) and test (5150, 9000) seeds


def pick_fixture(rng: random.Random) -> tuple[str, str, int]:
    from ..gen.model import load_league

    clubs = [c["team_id"] for c in load_league()["clubs"]]
    home, away = rng.sample(clubs, 2)
    return home, away, rng.randint(*SEEDS)


def make_feed(home: str, away: str, seed: int) -> Feed:
    """Generate the match and turn it into a provider's feed. Everything else is deleted."""
    from ..gen import generate_match
    from ..gen.cli import write_one

    m = generate_match(home, away, seed, match_id=f"unseen-{home}-{away}-{seed}")
    tmp = Path(tempfile.mkdtemp(prefix="matchlens-"))
    try:
        folder = write_one(tmp / "source", m.match_id, m.home, m.away, m.seed, m.events, m.physical.rows, [], [])
        feed_dir = export_feed(folder, tmp / "feed", load_mapping())
        shutil.rmtree(tmp / "source")  # the generator's folder and truth file: never sent, now gone
        return read_feed(feed_dir)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@dataclass
class Snapshot:
    version: int
    body: bytes
    gz: bytes


@dataclass
class Job:
    id: str
    home: str
    away: str
    seed: int
    foundry: Runner | None = None  # None: the rules explain this match
    budget: DailyBudget | None = None
    note: str = ""  # why the rules are explaining, for the screen
    drill: Drill | None = None  # an agent knocked out on purpose (the admin screen's fault drill)
    pace: float = PACE
    status: str = "generating"  # generating | playing | done | failed
    created: float = field(default_factory=time.time)
    ready: int = 0
    snapshot: Snapshot | None = None
    by: dict[str, int] = field(default_factory=lambda: {"foundry": 0, "rules": 0})
    live: LiveRunner | None = None
    _offline: OfflineRunner = field(default_factory=OfflineRunner)
    _guarded: dict[int, FailoverRunner] = field(default_factory=dict)
    _counted: int = 0
    _built_at: float = 0.0

    @property
    def agents_on(self) -> bool:
        return self.foundry is not None

    def _runner(self, runner: Runner) -> FailoverRunner:
        """`runner` with the retry, the rules stand-in and the drill (one wrapper per runner)."""
        if id(runner) not in self._guarded:
            self._guarded[id(runner)] = FailoverRunner(runner, OfflineRunner(), self.drill)
        return self._guarded[id(runner)]

    @property
    def incidents(self) -> int:
        return sum(r.incidents for r in self._guarded.values())

    def _drop_agents(self, why: str) -> None:
        if self.foundry is not None:
            log.warning("match %s: rules from %s' on: %s", self.id, self.ready, why)
            self.note = why
            self.foundry = None

    def _count_calls(self) -> None:
        """Book the model calls made since last time against today's budget; stop at the cap."""
        if self.foundry is None or self.budget is None:
            return
        calls = self.foundry.usage.calls
        self.budget.add_calls(calls - self._counted)
        self._counted = calls
        if self.budget.calls_left() <= 0:
            self._drop_agents("Today's AI budget ran out mid-match, so the rules write the rest.")

    # ---- the live explainer and on-screen writers, with the rules behind them ----

    async def explain(self, md: MatchData, m: Moment) -> dict[str, Any]:
        from ..agents.crew import explain_moment

        self._count_calls()
        happened = recording()  # this card's incidents
        if self.foundry is not None:
            try:
                card = await asyncio.wait_for(explain_moment(self._runner(self.foundry), md, m), MOMENT_TIMEOUT)
                stood_in = any(i["agent"] == "explainer" and i["recovered_by"] == "standby" for i in happened)
                card["written_by"] = "rules" if card["agents"]["fallback"] or stood_in else "foundry"
                return _logged(card, happened)
            except TimeoutError:
                self._drop_agents("Foundry was slow to answer, so the rules write the rest of this match.")
            except Exception as exc:  # any SDK failure: the screen must keep going
                log.warning("match %s: crew failed: %s", self.id, exc)
                self._drop_agents("Foundry could not be reached, so the rules write the rest of this match.")
        happened.clear()  # what Foundry did is gone with its card: the rules write this one afresh
        card = await explain_moment(self._runner(self._offline), md, m)
        card["written_by"] = "rules"
        return _logged(card, happened)

    async def finish(self, md: MatchData, shown: list[dict[str, Any]]) -> None:
        if self.foundry is not None:
            try:
                await asyncio.wait_for(asyncio.gather(*(self._write(self.foundry, md, c) for c in shown)), FINISH_TIMEOUT)
                return
            except TimeoutError:
                self._drop_agents("Foundry was slow to answer, so the rules write the rest of this match.")
            except Exception as exc:
                log.warning("match %s: writers failed: %s", self.id, exc)
                self._drop_agents("Foundry could not be reached, so the rules write the rest of this match.")
        for c in shown:
            c["written_by"] = "rules"
        await asyncio.gather(*(self._write(self._offline, md, c) for c in shown))

    async def _write(self, runner: Runner, md: MatchData, card: dict[str, Any]) -> None:
        """The Interpreter's and the Analyst's lines for one card, with their incidents on the card."""
        from ..agents.analyst import analyse_cards
        from ..agents.interpreter import interpret_cards

        happened = recording()
        guarded = self._runner(runner)
        try:
            await asyncio.gather(interpret_cards(guarded, md, [card]), analyse_cards(guarded, md, [card]))
        finally:
            _logged(card, happened, writers=True)

    # ---- playing it ----

    async def run(self) -> None:
        try:
            feed = await asyncio.to_thread(make_feed, self.home, self.away, self.seed)
            self.status = "playing"
            self.live = LiveRunner(feed.meta, self.explain, self.finish)
            for minute in feed.minutes:
                t0 = time.monotonic()
                shown = await self.live.add(minute)
                for c in shown:
                    self.by["rules" if c.get("written_by") == "rules" else "foundry"] += 1
                self.ready = self.live.match.minutes
                self._count_calls()
                if shown or time.monotonic() - self._built_at >= REBUILD:
                    self.publish(self.bundle())
                await asyncio.sleep(max(0.0, self.pace - (time.monotonic() - t0)))
            b = self.bundle(final=True)
            await self.full_time(b)
            self.status = "done"
            self.publish(b)
        except Exception:
            log.exception("match %s failed", self.id)
            self.status = "failed"
            self.note = "Something went wrong generating this match. Try another, or watch a demo match."
            self.publish(self.bundle() if self.live and self.ready else {"live": self.info()})
        finally:
            self._count_calls()
            if self.foundry is not None:
                await self.foundry.close()

    async def full_time(self, b: dict[str, Any]) -> None:
        """The Recapper's headlines and the Translator's Spanish, when the agents are still on."""
        if self.foundry is None:
            return
        from ..agents.recapper import recap_bundle
        from ..agents.translator import AgentBackend, translate_bundle

        try:
            await asyncio.wait_for(
                asyncio.gather(recap_bundle(self.foundry, b), translate_bundle(AgentBackend(self.foundry), b)), RECAP_TIMEOUT
            )
            b["recap"]["agents"]["usage"] = self.foundry.usage.as_dict()
        except Exception as exc:  # the rules' recap and Spanish are already in the bundle
            log.warning("match %s: recap or Spanish failed: %s", self.id, exc)
            b["recap"]["agents"] = None
        # what the services did over the whole match, for the admin screen and for checking the live site
        agents = b.get("agents") or {}
        agents["runner"] = "foundry"
        if (safety := getattr(self.foundry, "safety", None)) is not None:
            agents["content_safety"] = safety.count.as_dict()
        if (bridge := getattr(self.foundry, "mcp", None)) is not None:
            agents["mcp"] = bridge.as_dict()
        b["agents"] = agents

    def info(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seed": self.seed,
            "status": self.status,
            "ready": self.ready,
            "done": self.status == "done",
            "agents": "foundry" if self.agents_on else "rules",
            "note": self.note,
            "drill": self.drill.as_dict() if self.drill else None,
            "incidents": self.incidents,
            "by": dict(self.by),
            "calls": self._counted,
            "pace": self.pace,
            "truth_used": False,
        }

    def bundle(self, final: bool = False) -> dict[str, Any]:
        """The screen's bundle for the match so far (docs/broadcast.md), plus `live`. `final`: the
        feed has ended, so the timeline spans the real length."""
        assert self.live is not None
        md = self.live.match.md
        b = build(md, self.live.result())
        b["minutes"] = self.ready if final else max(SPAN, self.ready + 1)
        b["synthetic"] = True
        b["unseen"] = True
        b["live"] = self.info()
        return b

    def publish(self, b: dict[str, Any]) -> None:
        b["live"] = self.info()
        body = json.dumps(b, separators=(",", ":"), ensure_ascii=False).encode()
        version = (self.snapshot.version + 1) if self.snapshot else 1
        self.snapshot = Snapshot(version, body, gzip.compress(body, 6))
        self._built_at = time.monotonic()


WRITERS = ("interpreter", "analyst")


def _logged(card: dict[str, Any], log: list[dict[str, Any]], writers: bool = False) -> dict[str, Any]:
    """Put a step's incidents on its card. `writers`: the Interpreter's and Analyst's step, which
    replaces that step's incidents from an earlier try and keeps the explaining step's."""
    kept = [i for i in card.get("recovery") or [] if not writers or i["agent"] not in WRITERS]
    if kept or log:
        card["recovery"] = kept + list(log)
    return card
