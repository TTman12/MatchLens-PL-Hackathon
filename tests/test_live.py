"""Generate match on the live site (swing/live): the budget, the rate limit, a generated match
played as an unseen match, the rules taking over when the agents can't, and the HTTP API."""

from __future__ import annotations

import asyncio
import gzip
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from swing.agents.runners import OfflineRunner, Usage
from swing.live import job as job_mod
from swing.live.job import Job, make_feed
from swing.live.limits import CALLS_PER_MATCH, DailyBudget, RateLimit
from swing.live.server import Live, make_server

HOME, AWAY, SEED = "ash", "kes", 424242


def test_budget_counts_matches_and_calls_and_resets_each_day(tmp_path: Path) -> None:
    day = ["2026-10-21"]
    path = tmp_path / "budget.json"
    b = DailyBudget(path, matches=2, calls=3 * CALLS_PER_MATCH, clock=lambda: day[0])
    assert b.start_match() and b.start_match()
    assert not b.start_match()  # two a day
    b.add_calls(50)
    assert DailyBudget(path, 2, 3 * CALLS_PER_MATCH, clock=lambda: day[0]).as_dict()["ai_matches_left"] == 0  # kept on disk
    day[0] = "2026-10-22"
    assert b.start_match() and b.calls_left() == 3 * CALLS_PER_MATCH


def test_budget_needs_room_for_a_whole_match() -> None:
    b = DailyBudget(None, matches=5, calls=CALLS_PER_MATCH + 10)
    b.add_calls(20)
    assert not b.start_match()


def test_rate_limit_per_visitor() -> None:
    now = [0.0]
    r = RateLimit(2, 60, clock=lambda: now[0])
    assert r.allow("a") == 0 and r.allow("a") == 0
    assert r.allow("a") == pytest.approx(60)
    assert r.allow("b") == 0  # someone else
    now[0] = 61
    assert r.allow("a") == 0


def test_the_feed_carries_no_result_seed_or_truth() -> None:
    feed = make_feed(HOME, AWAY, SEED)
    assert "final_score" not in feed.meta and "seed" not in feed.meta
    assert [t["team_id"] for t in feed.meta["teams"]] == [HOME, AWAY]
    assert feed.minutes[0].m == 0 and len(feed.minutes) > 90
    kinds = {e["kind"] for m in feed.minutes for e in m.events}
    assert kinds <= {"period_start", "goal", "yellow_card", "second_yellow", "red_card", "substitution"}


def _play(job: Job) -> list[dict[str, Any]]:
    """Run the job; return every bundle it published, in order."""
    seen: list[dict[str, Any]] = []
    publish = job.publish

    def keep(b: dict[str, Any]) -> None:
        publish(b)
        assert job.snapshot is not None
        seen.append(json.loads(job.snapshot.body))

    job.publish = keep  # type: ignore[method-assign]
    asyncio.run(job.run())
    return seen


def test_a_generated_match_arrives_minute_by_minute_and_finishes() -> None:
    job = Job("t1", HOME, AWAY, SEED, pace=0)
    bundles = _play(job)
    assert job.status == "done"
    first, last = bundles[0], bundles[-1]
    assert first["live"]["ready"] < last["live"]["ready"]
    assert not first["live"]["done"] and first["minutes"] >= job_mod.SPAN  # the span until full time
    assert len(first["clock"]) == first["live"]["ready"]  # never a minute that hasn't arrived
    for b in bundles:
        assert all(c["at"] <= b["live"]["ready"] for c in b["cards"])
    assert last["live"]["done"] and last["minutes"] == last["live"]["ready"] == len(last["clock"])
    assert last["unseen"] and last["live"]["truth_used"] is False and last["live"]["seed"] == SEED
    assert last["cards"] and all(c["by"] == "rules" for c in last["cards"])
    assert last["live"]["by"] == {"foundry": 0, "rules": len(last["cards"])}
    assert last["recap"] and last["follow"]  # full time: the recap and follow-a-player are there
    assert gzip.decompress(job.snapshot.gz) == job.snapshot.body  # type: ignore[union-attr]


@dataclass
class StandIn:
    """Answers like Foundry would (the offline rules), and counts its calls the same way."""

    name: str = "foundry"
    usage: Usage = field(default_factory=Usage)
    delay: float = 0.0
    closed: bool = False

    async def run(self, role: Any, prompt: str, tools: Any, job: Any) -> str:
        if self.delay:
            await asyncio.sleep(self.delay)
        r = OfflineRunner()
        out = await r.run(role, prompt, tools, job)
        self.usage.calls += 1
        return out

    async def close(self) -> None:
        self.closed = True


def test_the_agents_write_the_cards_and_their_calls_are_booked() -> None:
    budget = DailyBudget(None, matches=5, calls=10_000)
    runner = StandIn()
    job = Job("t2", HOME, AWAY, SEED, foundry=runner, budget=budget, pace=0)
    last = _play(job)[-1]
    assert last["cards"] and all(c["by"] == "foundry" for c in last["cards"])
    assert runner.usage.calls > 0 and budget.calls_left() == 10_000 - runner.usage.calls
    assert runner.closed and last["live"]["note"] == ""
    assert last["agents"]["runner"] == "foundry"  # a stand-in without Content Safety or MCP adds no counts


def test_the_rules_take_over_when_the_budget_runs_out_mid_match() -> None:
    budget = DailyBudget(None, matches=5, calls=12)
    job = Job("t3", HOME, AWAY, SEED, foundry=StandIn(), budget=budget, pace=0)
    last = _play(job)[-1]
    assert job.status == "done" and not job.agents_on
    assert "budget" in last["live"]["note"] and last["live"]["agents"] == "rules"
    assert any(c["by"] == "rules" for c in last["cards"])


def test_the_rules_take_over_when_foundry_is_slow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_mod, "MOMENT_TIMEOUT", 0.05)
    job = Job("t4", HOME, AWAY, SEED, foundry=StandIn(delay=1.0), pace=0)
    last = _play(job)[-1]
    assert job.status == "done" and "slow" in last["live"]["note"]
    assert last["cards"] and all(c["by"] == "rules" for c in last["cards"])


# ---- the HTTP API ----


@pytest.fixture
def site(tmp_path: Path) -> Any:
    (tmp_path / "index.html").write_text("<p>screen</p>")
    live = Live("offline", DailyBudget(None, 5, 850), RateLimit(2, 3600), pace=0.0)
    server = make_server(tmp_path, 0, live, host="127.0.0.1")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _req(url: str, method: str = "GET") -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_generate_then_poll_until_full_time(site: str) -> None:
    with urllib.request.urlopen(site + "/healthz") as r:
        assert r.read() == b"ok\n"
    with urllib.request.urlopen(site + "/") as r:
        assert b"screen" in r.read()  # the screen is still served
    code, started = _req(site + "/api/generate", "POST")
    assert code == 202 and started["agents"] == "rules" and started["note"]
    deadline = time.time() + 60
    b: dict[str, Any] = {}
    while time.time() < deadline:
        code, b = _req(f"{site}/api/live/{started['id']}")
        assert code == 200
        if b["live"]["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert b["live"]["status"] == "done" and b["live"]["seed"] == started["seed"]
    assert _req(site + "/api/live/nope")[0] == 404


def test_a_visitor_is_rate_limited(site: str) -> None:
    assert _req(site + "/api/generate", "POST")[0] == 202
    assert _req(site + "/api/generate", "POST")[0] == 202
    code, body = _req(site + "/api/generate", "POST")
    assert code == 429 and body["retry_after"] > 0
