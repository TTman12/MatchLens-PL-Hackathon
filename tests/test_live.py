"""The condensed clock and the live server, on the sample match, offline."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from matchlens.agents.providers import ChaosProvider, OfflineProvider
from matchlens.api.clock import MAX_RATE, Span, merge, rate_at, slow_spans
from matchlens.api.live import LiveSession

from .agt_helpers import run
from .conftest import SAMPLE


def test_rate_is_real_time_inside_a_moment_and_eases_up_outside() -> None:
    spans = [Span(100.0, 130.0)]
    assert rate_at(115.0, spans) == 1.0
    assert rate_at(100.0, spans) == 1.0
    assert 1.0 < rate_at(95.0, spans) < rate_at(85.0, spans) < MAX_RATE
    assert rate_at(10.0, spans) == pytest.approx(MAX_RATE)
    assert rate_at(10.0, []) == pytest.approx(MAX_RATE)


def test_close_moments_merge_into_one_slow_stretch() -> None:
    assert merge([Span(10, 20), Span(30, 40), Span(100, 110)]) == [Span(10, 40), Span(100, 110)]


def test_slow_spans_cover_each_important_moment_and_its_boxes() -> None:
    result = run()
    spans = slow_spans(result.moments, result.cues.cues)
    for m in result.moments:
        boxes = [
            c
            for c in result.cues.cues
            if c.moment_id == m.moment_id and str(c.template) in ("replay", "fact_box")
        ]
        inside = [s for s in spans if s.start <= m.t_start and s.end >= m.t_end]
        assert inside, m.moment_id
        for c in boxes:
            assert inside[0].end >= c.t_show + c.duration


def test_dicts_and_contract_objects_give_the_same_spans() -> None:
    result = run()
    as_json = json.loads(result.cues.model_dump_json())["cues"]
    moments = [m.model_dump(mode="json") for m in result.moments]
    assert slow_spans(moments, as_json) == slow_spans(result.moments, result.cues.cues)


def _session(**kw: Any) -> LiveSession:
    return LiveSession(SAMPLE, lambda: OfflineProvider(), lead_s=60.0, **kw)


async def _play(session: LiveSession, wall_s: float, step: float = 0.05) -> float:
    """Runs the clock for up to ``wall_s`` seconds of pretend wall time, or to the end.

    The offline agents take next to no time, so each step lets them finish whatever the
    head released before the clock moves on. Returns the wall time used."""
    session.start_clock()
    await session.drain()
    wall = 0.0
    while wall < wall_s and session.ended_at is None:
        session.advance(step)
        wall += step
        await session.drain()
    return wall


def test_the_clock_waits_for_the_first_viewer() -> None:
    session = _session()
    session.advance(10.0)
    assert session.v == session.start
    assert session.clock()["started"] is False


def test_viewers_get_nothing_past_the_head() -> None:
    session = _session()
    body = json.loads(session.poll(0, 0, 0, 0))
    head = body["clock"]["head"]
    assert head == pytest.approx(session.start + 60.0)
    assert body["frames"] and body["frames"][-1]["t"] <= head
    assert all(e["t"] <= head for e in body["events"])
    assert len(body["frames"]) == sum(1 for t in session.frame_times if t <= head)


def test_moments_go_to_the_agents_only_once_the_head_has_passed_them() -> None:
    session = _session()

    ids = lambda: [m["moment_id"] for m in session.released.moments]  # noqa: E731

    async def go() -> None:
        assert ids() == []
        session.start_clock()  # head at 60 s: the corner ended at 38 s, the goal at 60 s
        assert ids() == ["m017-mo01"]
        while session.head < 100.0:
            session.advance(0.05)
            await session.drain()

    asyncio.run(go())
    assert ids() == ["m017-mo01", "m017-mo02"]
    assert all(m["t_end"] + 10.0 <= session.head for m in session.released.moments)


def test_a_whole_live_match_publishes_the_same_cues_as_the_batch_run() -> None:
    session = _session(pace="realtime")
    asyncio.run(_play(session, 200.0))
    assert session.clock()["ended"] is True
    assert session.released.late == 0
    batch = run().cues.model_dump(mode="json", exclude_none=True)["cues"]

    def key(c: dict[str, Any]) -> tuple[Any, ...]:
        return (c["t_show"], c["layer"], c["template"], c.get("player_id"), c["lang"])

    live = sorted(
        ({k: v for k, v in c.items() if k != "cue_id"} for c in session.released.cues), key=key
    )
    assert live == sorted(({k: v for k, v in c.items() if k != "cue_id"} for c in batch), key=key)
    assert len({c["cue_id"] for c in session.released.cues}) == len(session.released.cues)


def test_a_cue_that_arrives_after_viewers_passed_it_is_dropped() -> None:
    session = _session(pace="realtime")
    session.start_clock()
    session.v = 150.0
    session._publish(
        [
            {
                "match_id": "m017",
                "moment_id": "m017-mo02",
                "t_show": 60.0,
                "duration": 8.0,
                "layer": "global",
                "template": "timeline_item",
                "lang": "en",
                "box": {"headline": "Late", "body": ""},
            }
        ]
    )
    assert session.released.cues == []
    assert session.released.late == 1


def test_the_condensed_clock_is_quicker_but_plays_every_moment_at_real_time() -> None:
    session = _session()

    wall = asyncio.run(_play(session, 10_000.0))
    assert session.clock()["ended"] is True
    spans = session.spans
    slow = sum(min(s.end, session.end) - max(s.start, session.start) for s in spans)
    assert spans[0].start <= 17.2  # the first moment's build-up, at real time
    assert slow <= wall < session.end - session.start


def test_reset_goes_back_to_kick_off() -> None:
    session = _session(pace="realtime")
    asyncio.run(_play(session, 60.0))
    assert session.released.moments
    session.reset()
    assert session.v == session.start
    assert session.released.moments == [] and session.released.cues == []


def test_a_bare_link_opens_the_live_match(tmp_path: Any) -> None:
    from starlette.testclient import TestClient

    from matchlens.api.live import create_app

    (tmp_path / "index.html").write_text("<html>player</html>")
    app = create_app(LiveSession(SAMPLE, lambda: OfflineProvider()), web_dir=tmp_path)
    client = TestClient(app)
    bare = client.get("/", follow_redirects=False)
    assert bare.status_code == 307 and bare.headers["location"] == "/?live"
    assert client.get("/?live").text == "<html>player</html>"
    assert client.get("/healthz").status_code == 200


def test_live_replays_model_answers_with_the_budget_from_the_environment() -> None:
    from matchlens.agents.providers import ReplayProvider
    from matchlens.api.live import replay_from_env

    assert isinstance(replay_from_env(OfflineProvider()), OfflineProvider)
    wrapped = replay_from_env(
        ChaosProvider(OfflineProvider()), {"MATCHLENS_DAILY_MODEL_CALLS": "850"}
    )
    assert isinstance(wrapped, ReplayProvider) and wrapped.daily_budget == 850
