from pathlib import Path

import pytest

from swing.agents.crew import explain_match
from swing.explain.match import load
from swing.gen import generate_match
from swing.gen.cli import write_one


def test_a_match_is_one_trace_with_the_code_steps_and_agents_inside(tmp_path: Path) -> None:
    sdk = pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry import trace
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = sdk.TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    trace_get_tracer = trace.get_tracer
    trace.get_tracer = lambda *a, **k: tracer  # type: ignore[assignment]
    try:
        m = generate_match("ash", "brk", 40)
        mgr = m.manager
        folder = write_one(tmp_path, m.match_id, m.home, m.away, 40, m.events, m.physical.rows, mgr.decisions, mgr.minutes)
        md = load(folder)
        result = explain_match(md, "offline")
    finally:
        trace.get_tracer = trace_get_tracer  # type: ignore[assignment]

    spans = exporter.get_finished_spans()
    by_id = {s.context.span_id: s for s in spans}
    (root,) = [s for s in spans if s.parent is None]
    assert root.name == f"swing.match {md.meta['match_id']}"
    assert {s.context.trace_id for s in spans} == {root.context.trace_id}
    moments = [s for s in spans if s.name.startswith("swing.moment")]
    assert len(moments) == len(result["cards"])
    specialists = [s for s in spans if s.name.startswith("swing.specialist")]
    assert len(specialists) == 4 * len(moments)
    assert all(by_id[s.parent.span_id].name.startswith("swing.moment") for s in specialists if s.parent)
    verifier = [s for s in spans if s.name == "swing.verifier"]
    assert verifier and all(s.attributes and s.attributes["swing.passed"] for s in verifier)
    assert {s.attributes["swing.cause"] for s in moments if s.attributes} == {c["cause"]["kind"] for c in result["cards"]}


def test_tracing_is_set_up_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from swing import telemetry

    calls: list[str] = []

    class Project:
        class telemetry:  # noqa: N801 - mirrors AIProjectClient.telemetry
            @staticmethod
            async def get_application_insights_connection_string() -> str:
                calls.append("asked")
                await asyncio.sleep(0)
                return ""

    monkeypatch.setitem(telemetry._state, "exporting", False)
    monkeypatch.delenv(telemetry.CONNECTION_VAR, raising=False)

    async def many() -> list[bool]:
        return list(await asyncio.gather(*(telemetry.connect(Project()) for _ in range(8))))

    assert asyncio.run(many()) == [False] * 8
    assert asyncio.run(telemetry.connect(Project())) is False
    assert calls == ["asked"]
