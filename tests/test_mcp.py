import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from swing.agents import mcp_server
from swing.agents.crew import Job, explain_match, explain_match_async, offline_answer
from swing.agents.mcp_server import McpBridge
from swing.agents.roles import EXPLAINER, Role
from swing.agents.runners import ToolSpec, Usage
from swing.explain.match import load
from swing.gen import generate_match
from swing.gen.cli import write_one

pytest.importorskip("mcp")


def _write(tmp: Path, home: str, away: str, seed: int) -> Path:
    m = generate_match(home, away, seed)
    return write_one(tmp, m.match_id, m.home, m.away, seed, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes)


def _key(c: dict[str, Any]) -> tuple[Any, ...]:
    return (c["at"], c["cause"]["kind"], c["cause"].get("team"), [(s["label"], s["team"], s["after"]) for s in c["stats"]])


async def _call(fn: Any, **args: Any) -> str:
    """Call a tool the way Agent Framework does, by keyword."""
    out = fn(**args)
    return str(await out) if inspect.isawaitable(out) else str(out)


class OverMcp:
    """The offline answers, with every tool call made the way the Foundry runner makes it."""

    name = "over-mcp"

    def __init__(self, bridge: McpBridge) -> None:
        self.usage = Usage()
        self.mcp = bridge

    async def run(self, role: Role, prompt: str, tools: list[ToolSpec], job: Job) -> str:
        assert all(t.via is not None for t in tools)
        if role is EXPLAINER:
            answer = json.loads(offline_answer(role, tools, job))
            checked = json.loads(await _call(self.mcp.wrap(tools[0]), cause=answer["cause"], stats=answer["stats"]))
            assert checked["ok"], checked
            return json.dumps(answer)
        await _call(self.mcp.wrap(tools[0]))  # posts the findings, over MCP
        return offline_answer(role, tools, job)

    async def close(self) -> None:
        await self.mcp.close()


def test_the_crew_over_mcp_writes_the_same_cards(tmp_path: Path) -> None:
    md = load(_write(tmp_path, "ash", "brk", 40))
    runner = OverMcp(McpBridge())

    async def go() -> dict[str, Any]:
        try:
            return await explain_match_async(md, runner)
        finally:
            await runner.close()

    result = asyncio.run(go())
    cards = result["cards"]
    assert [_key(c) for c in cards] == [_key(c) for c in explain_match(md, "offline")["cards"]]
    assert not any(c["agents"]["fallback"] for c in cards)
    mcp = result["agents"]["mcp"]
    assert mcp["fallbacks"] == 0 and mcp["calls"] == 5 * len(cards)  # four specialists and one check per moment
    assert not [k for k in mcp_server.JOBS if k.startswith(md.meta["match_id"] + "@")]  # every board is closed afterwards


def test_a_failed_mcp_call_runs_the_tool_directly(tmp_path: Path) -> None:
    md = load(_write(tmp_path, "cal", "dun", 41))
    bridge = McpBridge()

    async def broken(name: str, args: dict[str, Any]) -> str:
        raise RuntimeError("server gone")

    bridge.call = broken  # type: ignore[method-assign]
    result = asyncio.run(explain_match_async(md, OverMcp(bridge)))
    assert [_key(c) for c in result["cards"]] == [_key(c) for c in explain_match(md, "offline")["cards"]]
    assert not any(c["agents"]["fallback"] for c in result["cards"])
    assert result["agents"]["mcp"]["calls"] == 0 and result["agents"]["mcp"]["fallbacks"] == 5 * len(result["cards"])


def test_off_switch_leaves_the_tools_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(mcp_server.MCP_VAR, "off")
    spec = ToolSpec("t", "d", lambda: "x", ("investigate", {"job": "j"}))
    assert McpBridge().wrap(spec) is spec.fn


def test_the_standalone_server_opens_a_moment_and_works_its_board(tmp_path: Path) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    folder = _write(tmp_path, "brk", "cal", 7)

    async def go() -> None:
        async with create_connected_server_and_client_session(mcp_server.server(folder.parent)) as s:

            async def call(name: str, **args: Any) -> Any:
                r = await s.call_tool(name, args)
                assert not r.isError, r.content
                return json.loads("".join(c.text for c in r.content if hasattr(c, "text")))

            names = {t.name for t in (await s.list_tools()).tools}
            assert {"list_matches", "momentum", "moments", "open_moment", "investigate", "read_board", "check_card"} <= names
            assert folder.name in await call("list_matches")
            moment = (await call("moments", match_id=folder.name))[0]
            opened = await call("open_moment", match_id=folder.name, clock=moment["clock"])
            for key in ("team_play", "players", "substitutions", "match_events"):
                assert (await call("investigate", job=opened["job"], specialist=key))["posted"] >= 0
            board = await call("read_board", job=opened["job"])
            assert board["findings"] and board["cause_menu"]
            checked = await call("check_card", job=opened["job"], cause="C99", stats=[])
            assert not checked["ok"] and checked["problems"]

    asyncio.run(go())


def test_foundry_declares_the_same_tools_and_calls_them_over_mcp(tmp_path: Path) -> None:
    pytest.importorskip("agent_framework")
    from types import SimpleNamespace

    from swing.agents.crew import check_tool, specialist_tool
    from swing.agents.runners import FoundryRunner
    from swing.explain.watcher import watch

    md = load(_write(tmp_path, "dun", "ash", 42))
    m = watch(md)[-1]
    job = Job(md.until(m.now), m, md.clock_of(m.now - 1))
    job.mcp_id = mcp_server.register(job)
    specs = [specialist_tool(job, "team_play"), check_tool(job)]
    bridge = McpBridge()
    direct = FoundryRunner._tools(SimpleNamespace(mcp=_Off()), specs)  # type: ignore[arg-type]
    routed = FoundryRunner._tools(SimpleNamespace(mcp=bridge), specs)  # type: ignore[arg-type]
    for a, b in zip(direct, routed, strict=True):
        assert (a.name, a.description, a.parameters()) == (b.name, b.description, b.parameters())  # same published definition

    async def go() -> str:
        try:
            return "".join(str(getattr(c, "text", None) or "") for c in await routed[0].invoke(arguments={}))
        finally:
            await bridge.close()
            mcp_server.release(job.mcp_id)

    over_mcp = asyncio.run(go())
    assert bridge.calls == 1 and bridge.fallbacks == 0
    fresh = Job(md.until(m.now), m, job.clock)
    assert json.loads(over_mcp) == json.loads(specialist_tool(fresh, "team_play").fn())


class _Off(McpBridge):
    def __init__(self) -> None:
        super().__init__()
        self.off = True
