"""Replay: a looping live match pays the model once, and a daily budget caps the rest."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from matchlens.agents.pipeline import run_match
from matchlens.agents.providers import AgentTask, OfflineProvider, ReplayProvider

from .conftest import SAMPLE


class LooksUpAndCites(OfflineProvider):
    """A Player agent that looks up the player's season and cites what it found, as a
    Foundry agent does. Counts the calls that reach it."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, task: AgentTask) -> str:
        self.calls += 1
        reply = await super().complete(task)
        if task.agent != "player" or not task.tools:
            return reply
        lookup = next(f for f in task.tools if f.__name__ == "lookup_season_stats")
        found = json.loads(lookup(player_id=task.instance.split(":")[1]))
        data = json.loads(reply)
        data["evidence_ids"] += [f["evidence_id"] for f in found]
        return json.dumps(data)


class MemoryStore:
    def __init__(self) -> None:
        self.state: dict[str, Any] | None = None

    async def load(self) -> dict[str, Any] | None:
        return self.state

    async def save(self, state: dict[str, Any]) -> None:
        self.state = state


def cues(provider: Any) -> list[dict[str, Any]]:
    result = asyncio.run(run_match(SAMPLE, provider, languages=["en", "es"]))
    return result.cues.model_dump(mode="json")["cues"]


def evidence(provider: Any) -> list[list[str]]:
    result = asyncio.run(run_match(SAMPLE, provider, languages=["en"]))
    return [[e.source for e in m.evidence] for m in result.moments]


def test_a_replayed_match_matches_the_first_and_calls_no_model() -> None:
    model = LooksUpAndCites()
    replay = ReplayProvider(model)
    first = cues(replay)
    calls = model.calls
    assert calls and replay.model_calls == calls
    assert cues(replay) == first
    assert model.calls == calls  # nothing new reached the model
    assert replay.replayed == calls


def test_replay_re_runs_the_lookups_so_their_evidence_is_back() -> None:
    replay = ReplayProvider(LooksUpAndCites())
    first = evidence(replay)
    assert any(s.startswith("season:") for m in first for s in m)
    assert evidence(replay) == first


def test_past_the_daily_budget_unseen_tasks_get_templates() -> None:
    model = LooksUpAndCites()
    replay = ReplayProvider(model, daily_budget=0)
    assert cues(replay) == cues(OfflineProvider())
    assert model.calls == 0 and replay.over_budget > 0


def test_the_budget_resets_each_day() -> None:
    now = [0.0]
    model = LooksUpAndCites()
    replay = ReplayProvider(model, daily_budget=3, clock=lambda: now[0])
    cues(replay)
    assert model.calls == 3
    now[0] += 86400
    replay._answers.clear()
    cues(replay)
    assert model.calls == 6


def test_a_store_carries_answers_and_the_count_across_restarts() -> None:
    store = MemoryStore()
    first = ReplayProvider(LooksUpAndCites(), daily_budget=1000, store=store)
    expected = cues(first)
    asyncio.run(first.close())
    assert store.state and store.state["spent"] == first.model_calls

    model = LooksUpAndCites()
    restarted = ReplayProvider(model, daily_budget=1000, store=store)
    assert cues(restarted) == expected
    assert model.calls == 0
    assert restarted._spent_today == first.model_calls
