"""Agent failover on a generated match (swing/live/failover.py): the retry, the rules stand-in,
the incidents on the cards, and the admin screen's fault drill through the HTTP API."""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from swing.agents.roles import EXPLAINER, INTERPRETER, PLAYERS, TEAM_PLAY
from swing.agents.runners import OfflineRunner, RunnerError, Usage
from swing.live import failover
from swing.live.failover import Drill, FailoverRunner, recording
from swing.live.job import Job
from swing.live.limits import DailyBudget, RateLimit
from swing.live.server import Live, make_server

HOME, AWAY, SEED = "ash", "kes", 424242


@pytest.fixture(autouse=True)
def no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(failover, "RETRY_DELAY", 0.0)


class Scripted:
    """A primary runner that fails the first `fails` calls, then answers "primary"."""

    name = "foundry"

    def __init__(self, fails: int = 0) -> None:
        self.fails = fails
        self.calls = 0
        self.usage = Usage()

    async def run(self, role: Any, prompt: str, tools: Any, job: Any) -> str:
        self.calls += 1
        if self.calls <= self.fails:
            raise RunnerError("model unavailable")
        return "primary"

    async def close(self) -> None:
        return None


class Standby(OfflineRunner):
    async def run(self, role: Any, prompt: str, tools: Any, job: Any) -> str:
        return "standby"


def _run(runner: FailoverRunner, role: Any) -> tuple[str, list[dict[str, Any]]]:
    async def go() -> tuple[str, list[dict[str, Any]]]:
        log = recording()
        return await runner.run(role, "", [], None), log  # type: ignore[arg-type]

    return asyncio.run(go())


def test_a_healthy_agent_answers_with_no_incident() -> None:
    r = FailoverRunner(Scripted(), Standby())
    assert _run(r, PLAYERS) == ("primary", [])
    assert r.incidents == 0 and r.name == "foundry"


def test_a_real_failure_goes_straight_to_the_stand_in() -> None:
    primary = Scripted(fails=5)
    r = FailoverRunner(primary, Standby())
    text, log = _run(r, PLAYERS)
    assert text == "standby" and primary.calls == 1  # the runner already retried it
    (inc,) = log
    assert inc["agent"] == "players" and inc["recovered_by"] == "standby" and not inc["drill"]
    assert [t["status"] for t in inc["tries"]] == ["failed", "answered"] and "unavailable" in inc["tries"][0]["error"]


def test_the_drill_knocks_out_only_its_agent_and_never_calls_it() -> None:
    primary = Scripted()
    r = FailoverRunner(primary, Standby(), Drill("players", "down"))
    text, log = _run(r, PLAYERS)
    assert text == "standby" and primary.calls == 0  # no model call for a drilled agent
    assert [t["try"] for t in log[0]["tries"]] == [1, 2, "stand-in"] and log[0]["drill"]
    assert _run(r, TEAM_PLAY) == ("primary", [])  # the others are untouched


def test_a_flaky_agent_is_answered_by_the_retry() -> None:
    primary = Scripted()
    text, log = _run(FailoverRunner(primary, Standby(), Drill("interpreter", "flaky")), INTERPRETER)
    assert text == "primary" and primary.calls == 1
    assert log[0]["recovered_by"] == "retry" and [t["status"] for t in log[0]["tries"]] == ["failed", "answered"]


def test_drill_parameters_are_checked() -> None:
    assert Drill.parse(None) is None
    assert Drill.parse("explainer") == Drill("explainer", "down")
    with pytest.raises(ValueError):
        Drill.parse("recapper")  # not one of the card's agents
    with pytest.raises(ValueError):
        Drill.parse("players", "slow")


@pytest.mark.parametrize("agent", ["players", "explainer", "interpreter"])
def test_a_drilled_match_still_puts_up_every_card_with_the_recovery_on_it(agent: str) -> None:
    job = Job("d1", HOME, AWAY, SEED, pace=0, drill=Drill(agent))
    asyncio.run(job.run())
    assert job.status == "done" and job.snapshot is not None
    b = json.loads(job.snapshot.body)
    assert b["live"]["drill"] == {"agent": agent, "mode": "down"} and b["live"]["incidents"] >= len(b["cards"]) > 0
    for c in b["cards"]:
        (inc,) = c["recovery"]
        assert inc["agent"] == agent and inc["drill"] and inc["recovered_by"] == "standby"
        h = c["hood"]
        assert h["verifier"][-1]["status"] == "passed"  # the Verifier still checked the card
        if agent == "interpreter":
            assert h["interpreter"]["rounds"][-1]["status"] == "passed"  # the stand-in's line passed its check
        assert c["text"]


def test_with_the_agents_on_only_the_drilled_agent_stops_calling_foundry() -> None:

    calls: dict[str, int] = {}

    class Counting(OfflineRunner):
        name = "foundry"

        async def run(self, role: Any, prompt: str, tools: Any, job: Any) -> str:
            calls[role.key] = calls.get(role.key, 0) + 1
            return await super().run(role, prompt, tools, job)

    job = Job("d2", HOME, AWAY, SEED, foundry=Counting(), budget=DailyBudget(None, 5, 10_000), pace=0, drill=Drill("explainer"))
    asyncio.run(job.run())
    b = json.loads(job.snapshot.body)  # type: ignore[union-attr]
    assert EXPLAINER.key not in calls and calls["players"] > 0
    assert all(c["by"] == "rules" for c in b["cards"])  # the stand-in chose: labelled as the rules'


# ---- the HTTP API ----


@pytest.fixture
def site(tmp_path: Path) -> Any:
    def serve(drills: RateLimit | None) -> str:
        live = Live("offline", DailyBudget(None, 5, 850), RateLimit(10, 3600), pace=0.0, drills=drills)
        server = make_server(tmp_path, 0, live, host="127.0.0.1")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    servers: list[Any] = []
    yield serve
    for s in servers:
        s.shutdown()


def _post(url: str) -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_drill_is_asked_for_by_query_and_rate_limited(site: Any) -> None:
    url = site(RateLimit(1, 3600))
    code, body = _post(url + "/api/generate?drill=players&drill_mode=flaky")
    assert code == 202 and body["drill"] == {"agent": "players", "mode": "flaky"}
    assert _post(url + "/api/generate?drill=players")[0] == 429  # one drill an hour here
    assert _post(url + "/api/generate")[0] == 202  # plain matches are still allowed
    assert _post(url + "/api/generate?drill=recapper")[0] == 400


def test_the_drill_can_be_switched_off(site: Any) -> None:
    url = site(None)
    code, body = _post(url + "/api/generate?drill=players")
    assert code == 403 and "off" in body["error"]
    with urllib.request.urlopen(url + "/api/live") as r:
        assert json.loads(r.read())["drills"] is False
