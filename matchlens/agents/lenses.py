"""The three lens agents: Player (fanned out per contributor), Club (per club) and Pundit.

Each lens has a deterministic **gate** that decides whether the moment deserves a box
for that lens at all, so no model call is spent on a routine yellow card. When the gate
opens, the lens builds an ``AgentTask`` and calls the provider through ``AgentCaller``,
which applies the timeout, one retry and, if both fail, the template fallback.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

from matchlens.contracts import ClaimType, Draft, Lens, MomentType
from matchlens.mcp_server.tools import MatchStateStore

from . import templates
from .providers import AgentTask, ModelProvider, ProviderError
from .state import DraftResult, LensOutput, MomentContext, TemplateRef
from .trace import AgentTrace

MAX_AGENT_BOXES_PER_MOMENT = 5
"""Top contributors get an agent-written box; anyone further down gets the template."""
PUNDIT_MIN_XG = 0.3
PUNDIT_MIN_DIFFICULTY = 0.65


@cache
def prompt(name: str) -> str:
    """Instructions for an agent: its own prompt plus the shared writing rules."""
    folder = resources.files("matchlens.agents") / "prompts"
    own = (folder / f"{name}.md").read_text(encoding="utf-8")
    if name == "translator":
        return own
    return own + "\n" + (folder / "_rules.md").read_text(encoding="utf-8")


def parse_json(reply: str) -> dict[str, Any]:
    """The first JSON object in a model reply, tolerating code fences and chatter."""
    text = reply.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ProviderError("reply has no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError(f"reply is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("reply is not a JSON object")
    return data


def moment_brief(ctx: MomentContext, store: MatchStateStore) -> dict[str, Any]:
    """The facts every lens prompt starts from."""
    m = ctx.moment
    match = store.match
    return {
        "moment_id": m.moment_id,
        "type": str(m.type),
        "match": f"{match.club_name(match.home_id)} v {match.club_name(match.away_id)}",
        "stakes": match.meta.stakes.notes,
        "importance": m.importance,
        "involved": [
            {
                "player_id": c.player_id,
                "name": ctx.names.get(c.player_id),
                "role": c.role,
                "team": ctx.names.get(match.team_of(c.player_id)),
            }
            for c in ctx.contributors
        ],
        "evidence": [{"id": i.id, "fact": i.value, "numbers": i.numbers} for i in ctx.ledger.items],
    }


class EvidenceTools:
    """Match-State lookups for a model agent. Each fact found is added to the moment's
    evidence, and the tool returns its id so the agent can cite it."""

    def __init__(self, ctx: MomentContext, store: MatchStateStore) -> None:
        self.ctx = ctx
        self.store = store

    def _register(self, result: dict[str, Any]) -> str:
        cited = []
        for f in result.get("facts", []):
            evidence_id = self.ctx.ledger.add(
                ClaimType(f["claim_type"]), f["value"], f["source"], f["numbers"]
            )
            cited.append({"evidence_id": evidence_id, "fact": f["value"]})
        self.ctx.sync()
        return json.dumps(cited)

    def functions(self) -> list[Callable[..., str]]:
        def lookup_season_stats(player_id: str) -> str:
            """League season stats for a player before this match (goals, assists, cards).
            Returns evidence ids you can cite."""
            return self._register(self.store.get_season_stats(player_id))

        def lookup_player_match_stats(player_id: str) -> str:
            """A player's stats in this match up to this moment. Returns evidence ids."""
            return self._register(
                self.store.get_player_match_stats(player_id, self.ctx.moment.t_peak)
            )

        def lookup_next_fixture(team_id: str) -> str:
            """A club's next league match. Returns evidence ids you can cite."""
            return self._register(self.store.get_fixtures(team_id))

        return [lookup_season_stats, lookup_player_match_stats, lookup_next_fixture]


@dataclass
class AgentCaller:
    """Calls the provider with a timeout and one retry, then falls back to the template."""

    provider: ModelProvider
    trace: AgentTrace
    timeout_s: float = 20.0
    retries: int = 1

    async def draft(
        self,
        ctx: MomentContext,
        key: str,
        task: AgentTask,
        lens: Lens,
        subject: str | None,
        fallback: TemplateRef,
    ) -> DraftResult:
        attempts = self.retries + 1
        last_error = ""
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                reply = await asyncio.wait_for(self.provider.complete(task), self.timeout_s)
                data = parse_json(reply)
                draft = self._to_draft(data, lens, subject, task.instance, ctx)
                template = _template_from(data)
                status = "ok" if attempt == 0 else "retried"
                detail = "no box" if draft.kind == "no_box" else draft.headline
                self.trace.add(
                    ctx.moment_id, task.agent, task.instance, "draft", status, detail, started
                )
                return DraftResult(key, draft, template, status)
            except (TimeoutError, ProviderError, ValueError) as exc:
                kind = "timeout" if isinstance(exc, TimeoutError) else "error"
                last_error = "timed out" if kind == "timeout" else str(exc)
                status = "retry" if attempt + 1 < attempts else kind
                self.trace.add(
                    ctx.moment_id, task.agent, task.instance, "draft", status, last_error, started
                )
        draft = templates.to_draft(fallback, lens, subject)
        self.trace.add(
            ctx.moment_id,
            task.agent,
            task.instance,
            "fallback",
            "fallback",
            f"template box after: {last_error}",
        )
        return DraftResult(
            key, draft, fallback, "timeout" if "timed out" in last_error else "error"
        )

    @staticmethod
    def _to_draft(
        data: dict[str, Any], lens: Lens, subject: str | None, instance: str, ctx: MomentContext
    ) -> Draft:
        kind = "no_box" if data.get("kind") == "no_box" else "box"
        ids = [str(i) for i in data.get("evidence_ids", []) if isinstance(i, str)]
        return Draft(
            lens=lens,
            subject_id=subject,
            kind=kind,
            headline=str(data.get("headline", "")) if kind == "box" else "",
            body=str(data.get("body", "")) if kind == "box" else "",
            evidence_ids=ids if kind == "box" else [],
            author="agent",
            agent=instance,
        )


def _template_from(data: dict[str, Any]) -> TemplateRef | None:
    t = data.get("template")
    if not isinstance(t, dict):
        return None
    return TemplateRef(
        str(t["key"]),
        dict(t["params"]),
        list(t["parts"]),
        [str(i) for i in data.get("evidence_ids", [])],
    )


def no_box(key: str, lens: Lens, subject: str | None, instance: str) -> DraftResult:
    return DraftResult(
        key, Draft(lens=lens, subject_id=subject, kind="no_box", agent=instance), None, "gated"
    )


# -- gates ------------------------------------------------------------------------------


def club_gate(ctx: MomentContext, team_id: str) -> bool:
    """Did this club's stakes change? Goals and red cards always; a yellow only with a ban."""
    m = ctx.moment
    if m.type is MomentType.GOAL:
        return True
    if m.type is MomentType.CARD:
        if ctx.facts.get("red"):
            return True
        return bool(ctx.facts.get("banned")) and ctx.facts.get("booked_team") == team_id
    return False


def pundit_gate(ctx: MomentContext) -> bool:
    """Brilliance or a shift in the game."""
    m = ctx.moment
    if m.type in (MomentType.GOAL, MomentType.SWING, MomentType.BIG_SAVE):
        return True
    if m.type is MomentType.BIG_CHANCE:
        return float(ctx.facts.get("xg", 0.0)) >= PUNDIT_MIN_XG
    if m.type is MomentType.CARD:
        return bool(ctx.facts.get("red"))
    return False


def player_gate(ctx: MomentContext) -> bool:
    """Corners alone are set-up, not a contribution worth a box."""
    return ctx.moment.type is not MomentType.CORNER


# -- the lenses -------------------------------------------------------------------------


class PlayerLens:
    """Fans out one Player agent per contributor, in parallel."""

    lens = Lens.PLAYER

    def __init__(self, caller: AgentCaller, store: MatchStateStore) -> None:
        self.caller = caller
        self.store = store

    async def run(self, ctx: MomentContext) -> LensOutput:
        if not player_gate(ctx):
            return LensOutput(
                self.lens,
                [
                    no_box(
                        f"player:{c.player_id}",
                        self.lens,
                        c.player_id,
                        f"player-agent:{c.player_id}",
                    )
                    for c in ctx.contributors
                ],
            )
        jobs = []
        for rank, c in enumerate(ctx.contributors):
            key = f"player:{c.player_id}"
            ref = templates.player_template(ctx, c.player_id)
            instance = f"player-agent:{c.player_id}"
            if rank >= MAX_AGENT_BOXES_PER_MOMENT:
                self.caller.trace.add(
                    ctx.moment_id,
                    "player",
                    instance,
                    "draft",
                    "skipped",
                    "below the top 5 contributors: template box",
                )
                jobs.append(
                    _done(
                        DraftResult(
                            key, templates.to_draft(ref, self.lens, c.player_id), ref, "capped"
                        )
                    )
                )
                continue
            brief = moment_brief(ctx, self.store) | {
                "lens": "player",
                "player": {
                    "player_id": c.player_id,
                    "name": ctx.names.get(c.player_id),
                    "role": c.role,
                },
            }
            task = AgentTask(
                agent="player",
                instance=instance,
                instructions=prompt("player"),
                prompt=json.dumps(brief),
                payload={"ctx": ctx, "template": ref},
                tier="fast",
                tools=EvidenceTools(ctx, self.store).functions(),
            )
            jobs.append(self.caller.draft(ctx, key, task, self.lens, c.player_id, ref))
        return LensOutput(self.lens, list(await asyncio.gather(*jobs)))


class ClubLens:
    lens = Lens.CLUB

    def __init__(self, caller: AgentCaller, store: MatchStateStore) -> None:
        self.caller = caller
        self.store = store

    async def run(self, ctx: MomentContext) -> LensOutput:
        match = self.store.match
        jobs = []
        for team_id in (match.home_id, match.away_id):
            key, instance = f"club:{team_id}", f"club-agent:{team_id}"
            if not club_gate(ctx, team_id):
                self.caller.trace.add(
                    ctx.moment_id,
                    "club",
                    instance,
                    "gate",
                    "skipped",
                    "stakes unchanged for this club: no box",
                )
                jobs.append(_done(no_box(key, self.lens, team_id, instance)))
                continue
            ref = templates.club_template(ctx, team_id, match.home_id, match.away_id)
            brief = moment_brief(ctx, self.store) | {
                "lens": "club",
                "club": {"team_id": team_id, "name": ctx.names.get(team_id)},
            }
            task = AgentTask(
                agent="club",
                instance=instance,
                instructions=prompt("club"),
                prompt=json.dumps(brief),
                payload={"ctx": ctx, "template": ref},
                tier="fast",
                tools=EvidenceTools(ctx, self.store).functions(),
            )
            jobs.append(self.caller.draft(ctx, key, task, self.lens, team_id, ref))
        return LensOutput(self.lens, list(await asyncio.gather(*jobs)))


class PunditLens:
    lens = Lens.PUNDIT

    def __init__(self, caller: AgentCaller, store: MatchStateStore) -> None:
        self.caller = caller
        self.store = store

    async def run(self, ctx: MomentContext) -> LensOutput:
        if not pundit_gate(ctx):
            self.caller.trace.add(
                ctx.moment_id,
                "pundit",
                "pundit-agent",
                "gate",
                "skipped",
                "nothing brilliant or game-changing: no box",
            )
            return LensOutput(self.lens, [no_box("pundit", self.lens, None, "pundit-agent")])
        match = self.store.match
        ref = templates.pundit_template(ctx, match.home_id, match.away_id)
        brief = moment_brief(ctx, self.store) | {
            "lens": "pundit",
            "momentum": self.store.get_momentum(ctx.moment.t_peak)["momentum"],
        }
        task = AgentTask(
            agent="pundit",
            instance="pundit-agent",
            instructions=prompt("pundit"),
            prompt=json.dumps(brief),
            payload={"ctx": ctx, "template": ref},
            tier="fast",
            tools=EvidenceTools(ctx, self.store).functions(),
        )
        return LensOutput(
            self.lens, [await self.caller.draft(ctx, "pundit", task, self.lens, None, ref)]
        )


async def _done(result: DraftResult) -> DraftResult:
    return result
