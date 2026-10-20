"""Detector, Verifier, Director, MCP server and providers, one piece at a time."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from matchlens.agents.director import Director, DirectorConfig
from matchlens.agents.lenses import AgentCaller, parse_json
from matchlens.agents.providers import (
    AgentFrameworkProvider,
    AgentTask,
    ChaosProvider,
    FoundrySettings,
    OfflineProvider,
    ProviderError,
    provider_from_env,
)
from matchlens.agents.state import DraftResult, VerifiedMoment
from matchlens.agents.trace import AgentTrace
from matchlens.agents.verifier import LocalToneChecker, Verifier
from matchlens.contracts import Draft, Lens
from matchlens.mcp_server import TOOL_NAMES, MatchStateStore

from .agt_helpers import evals_module, moments, stats

# -- Moment Detector ------------------------------------------------------------------------


def test_detector_roles_and_evidence() -> None:
    ctx = moments()
    goal = ctx["goal"]
    roles = {c.player_id: c.role for c in goal.contributors}
    assert roles["ash-09"] == "scorer" and roles["ash-08"] == "assist"
    assert roles["ash-06"] == "build_up"
    assert goal.facts["scorer"] == "ash-09" and goal.facts["derby"]
    assert goal.moment.win_prob_after.home > goal.moment.win_prob_before.home
    assert goal.suspense > 0 and goal.surprise > 0
    ids = [i.id for i in goal.ledger.items]
    assert len(ids) == len(set(ids)) and all(i.startswith("ev") for i in ids)

    card = ctx["card"]
    assert card.facts["banned"] and card.facts["booked"] == "ash-03"
    discipline = card.ledger.get("discipline")
    assert discipline is not None and discipline.numbers["yellows"] == 5


def test_detector_importance_is_ordered() -> None:
    ctx = moments()
    assert ctx["goal"].moment.importance > ctx["card"].moment.importance
    assert ctx["goal"].moment.importance > ctx["corner"].moment.importance


# -- Verifier -------------------------------------------------------------------------------


def test_verifier_eval_cases() -> None:
    results = asyncio.run(evals_module().run_cases())
    failed = [(r.case_id, r.expected, r.got, r.issues) for r in results if not r.passed]
    assert not failed
    assert {r.expected for r in results} == {"approved", "repaired", "rejected"}


def _draft(ctx: Any, headline: str, body: str, refs: Sequence[str], lens: str = "player") -> Draft:
    return Draft.model_construct(
        lens=Lens(lens),
        subject_id="ash-09" if lens == "player" else "ash",
        kind="box",
        headline=headline,
        body=body,
        evidence_ids=[ctx.ledger.refs[r] for r in refs],
        author="agent",
        agent="test-agent",
    )


def _verifier() -> Verifier:
    trace = AgentTrace()
    names = {pid: p.short_name for pid, p in stats().match.players.items()}
    return Verifier(AgentCaller(OfflineProvider(), trace), trace, player_names=names)


def test_verifier_rejects_a_wrong_number_and_adds_missing_citations() -> None:
    ctx = moments()["goal"]
    v = _verifier()
    wrong = asyncio.run(v.check(ctx, _draft(ctx, "Varrow at 37 km/h", "Quick.", ["run:ash-09"])))
    assert wrong.issues and not wrong.fixable
    uncited = asyncio.run(v.check(ctx, _draft(ctx, "Varrow at 34.3 km/h", "Quick.", ["shot"])))
    assert uncited.fixable and uncited.missing_citations == [ctx.ledger.refs["run:ash-09"]]


def test_verifier_flags_stray_names_and_tone() -> None:
    ctx = moments()["goal"]
    v = _verifier()
    others = [
        p.short_name
        for pid, p in stats().match.players.items()
        if not ctx.contributor(pid)
        and p.short_name not in " ".join(i.value for i in ctx.ledger.items)
    ]
    stray = asyncio.run(v.check(ctx, _draft(ctx, f"{others[0]} watches", "Nice.", [])))
    assert any("not part of this moment" in i for i in stray.issues)
    rude = asyncio.run(v.check(ctx, _draft(ctx, "Brackenford are useless", "Ha.", [], lens="club")))
    assert any("tone" in i for i in rude.issues) and not rude.fixable
    assert asyncio.run(LocalToneChecker().check("Get in! Derby day bragging rights.")) == []


def test_verifier_falls_back_to_the_template_when_repair_fails() -> None:
    ctx = moments()["goal"]
    v = _verifier()
    bad = _draft(ctx, "Varrow at 99 km/h", "He flew at 99 km/h.", ["run:ash-09"])
    approved = asyncio.run(v.verify(ctx, [DraftResult("player:ash-09", bad)]))
    verdict = ctx.moment.verdicts["player:ash-09"]
    assert verdict.status in ("repaired", "fallback")
    final = approved["player:ash-09"].draft
    assert "99" not in final.headline + final.body


# -- Director -------------------------------------------------------------------------------


def _approved(ctx: Any, keys: Sequence[str]) -> VerifiedMoment:
    draft = Draft.model_construct(
        lens=Lens.PLAYER, kind="box", headline="Box", body="Body.", evidence_ids=[]
    )
    return VerifiedMoment(ctx, {k: DraftResult(k, draft) for k in keys})


def _shown(cues: list[dict[str, Any]]) -> set[str]:
    return {c["_key"] for c in cues if str(c["template"]) == "fact_box"}


def test_director_card_without_ban_goes_to_the_timeline() -> None:
    ctx = moments()["card"]
    ctx.facts["banned"] = False
    cues = Director(stats(), AgentTrace()).schedule(_approved(ctx, ["player:ash-03"]))
    assert not _shown(cues)
    assert any(c.get("_key") == "player:ash-03" for c in cues if c["template"] == "timeline_item")


def test_director_cooldown_budget_and_separate_tracks() -> None:
    ctx = moments()
    d = Director(stats(), AgentTrace(), DirectorConfig(boxes_per_half=1))
    goal = ctx["goal"]
    assert _shown(d.schedule(_approved(goal, ["player:ash-09"]))) == {"player:ash-09"}
    # Same track, same half, budget of one: the next goal moment is cut to the timeline.
    goal.moment.moment_id += "b"
    assert not _shown(d.schedule(_approved(goal, ["player:ash-09"])))
    # Another player's track has its own budget.
    assert _shown(d.schedule(_approved(goal, ["player:ash-08"]))) == {"player:ash-08"}

    d = Director(stats(), AgentTrace())
    corner = ctx["corner"]
    corner.moment.importance = 1.0
    corner.moment.t_peak = goal.moment.t_peak - 60
    assert _shown(d.schedule(_approved(corner, ["pundit"]))) == {"pundit"}
    later = moments()["corner"]
    later.moment.importance = 1.0
    later.moment.t_peak = corner.moment.t_peak + 100  # inside the 4-minute cooldown
    assert not _shown(d.schedule(_approved(later, ["pundit"])))


def test_director_low_priority_goes_to_the_timeline() -> None:
    ctx = moments()["corner"]
    ctx.moment.importance = 0.1
    assert not _shown(Director(stats(), AgentTrace()).schedule(_approved(ctx, ["pundit"])))


def test_director_replays_in_dead_time() -> None:
    ctx = moments()
    d = Director(stats(), AgentTrace())
    goal = ctx["goal"]
    start, length = d.replay_slot(goal) or (0.0, 0.0)
    assert start == pytest.approx(goal.moment.t_peak + 2.0)
    assert length >= 4.0
    cues = d.schedule(_approved(goal, ["player:ash-09"]))
    box = next(c for c in cues if c.get("_key") == "player:ash-09")
    assert box["t_show"] >= start + length  # the box follows the replay
    replays = [c for c in cues if c["template"] == "replay" and c["layer"] == "player"]
    assert {c["player_id"] for c in replays} == {c.player_id for c in goal.contributors}


# -- Match-State MCP server -----------------------------------------------------------------


def test_mcp_server_lists_and_calls_tools() -> None:
    pytest.importorskip("mcp")
    store = MatchStateStore(stats())
    for ctx in moments().values():
        store.add_moment(ctx.moment)
    from matchlens.mcp_server.server import build_server

    server = build_server(store)

    async def go() -> tuple[list[str], Any]:
        tools = await server.list_tools()
        result = await server.call_tool("get_contribution", {"shot_event_id": "m017-e0026"})
        return [t.name for t in tools], result

    names, result = asyncio.run(go())
    assert sorted(names) == sorted(TOOL_NAMES)
    assert "ash-09" in json.dumps(result, default=str)


def test_mcp_store_facts_carry_sources() -> None:
    store = MatchStateStore(stats())
    out = store.get_season_stats("ash-09")
    assert out["facts"] and all(f["source"] for f in out["facts"])


# -- Providers ------------------------------------------------------------------------------


def test_provider_selection_from_env() -> None:
    assert isinstance(provider_from_env({}), OfflineProvider)
    assert isinstance(provider_from_env({"MATCHLENS_PROVIDER": "offline"}), OfflineProvider)
    chaos = provider_from_env({}, chaos=["kill:pundit"])
    assert isinstance(chaos, ChaosProvider) and chaos.kill == {"pundit"}
    with pytest.raises(ProviderError):
        provider_from_env({"MATCHLENS_PROVIDER": "openai"})
    with pytest.raises(ProviderError):
        FoundrySettings.from_env({"AZURE_AI_PROJECT_ENDPOINT": "https://x"})
    settings = FoundrySettings.from_env(
        {"AZURE_AI_PROJECT_ENDPOINT": "https://x", "AZURE_AI_MODEL_FAST": "fast"}
    )
    assert settings.strong_model == "fast"
    with pytest.raises(ValueError):
        ChaosProvider.from_rules(OfflineProvider(), ["explode:pundit"])


def test_parse_json_tolerates_fences_and_rejects_prose() -> None:
    assert parse_json('Sure!\n```json\n{"headline": "A"}\n```') == {"headline": "A"}
    assert parse_json('{"a": 1} trailing') == {"a": 1}
    with pytest.raises(ProviderError):
        parse_json("no json here")


def test_agent_framework_provider_runs_a_real_agent() -> None:
    """The Foundry path, with a scripted chat client in place of Foundry."""
    pytest.importorskip("agent_framework")
    from agent_framework import BaseChatClient, ChatResponse, Message

    class ScriptedClient(BaseChatClient):  # type: ignore[misc]
        def __init__(self, reply: str) -> None:
            super().__init__()
            self.reply = reply
            self.seen: list[Any] = []

        async def _inner_get_response(self, *, messages: Any, **kwargs: Any) -> ChatResponse:
            self.seen.append(messages)
            return ChatResponse(messages=[Message("assistant", [self.reply])])

        def _inner_get_streaming_response(self, **kwargs: Any) -> AsyncIterator[Any]:
            raise NotImplementedError

    client = ScriptedClient('{"headline": "Hi", "body": "There."}')
    provider = AgentFrameworkProvider({"fast": client, "strong": client})
    task = AgentTask(
        agent="player",
        instance="player-agent:ash-09",
        instructions="Write a box.",
        prompt="{}",
        payload={},
    )
    reply = asyncio.run(provider.complete(task))
    assert parse_json(reply)["headline"] == "Hi"
    assert client.seen

    empty = AgentFrameworkProvider({"fast": ScriptedClient(" "), "strong": client})
    with pytest.raises(ProviderError):
        asyncio.run(empty.complete(task))


# -- Evals ----------------------------------------------------------------------------------


def test_chaos_audits_pass() -> None:
    reports = asyncio.run(evals_module().run_chaos_audits())
    assert set(reports) >= {"clean", "every-lens-misquotes", "all-lens-agents-killed"}
    for name, report in reports.items():
        assert report.ok, (name, report.problems)
        assert report.numbers_checked > 0


def test_each_role_is_one_foundry_agent() -> None:
    from matchlens.agents.providers.foundry import foundry_agent_name

    def task(agent: str, tier: str = "fast") -> AgentTask:
        return AgentTask(agent=agent, instance=f"{agent}:x", instructions="", prompt="", tier=tier)  # type: ignore[arg-type]

    assert foundry_agent_name(task("player")) == "matchlens-player"
    assert foundry_agent_name(task("translator")) == "matchlens-translator"
    assert foundry_agent_name(task("pundit", "strong")) == "matchlens-pundit-brief"


def test_published_tool_schemas_are_strict() -> None:
    pytest.importorskip("agent_framework_foundry")
    from agent_framework import Agent
    from agent_framework_foundry import FoundryChatClient

    from matchlens.agents.providers.foundry import prompt_agent_definition

    def lookup_next_fixture(team_id: str) -> str:
        """A club's next league match."""
        return team_id

    client = FoundryChatClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        model="gpt-4.1-mini",
        credential=object(),  # never used: nothing is sent
    )
    agent = Agent(
        client=client,
        instructions="Write a box.",
        name="matchlens-club",
        tools=[lookup_next_fixture],
    )
    definition = prompt_agent_definition(agent)
    assert definition["model"] == "gpt-4.1-mini"
    (tool,) = definition["tools"]
    assert tool["name"] == "lookup_next_fixture"
    assert tool["parameters"]["additionalProperties"] is False
