"""The MatchLens MCP server: the match tables and the findings board, as Model Context Protocol tools.

The agents' tools are served by this server. When a Foundry specialist calls
``investigate_team_play``, or the Explainer calls ``check_card``, Agent Framework runs the tool and
the call goes over MCP to this server, which computes the findings from the match tables, posts
them to the moment's board, and answers. The pipeline adds which moment the call is about (the
``job`` argument), so each agent still sees only its own tool and that tool's own arguments.

    Foundry agent --function call--> Agent Framework --MCP tools/call--> MatchLens MCP server
                                                                           match tables, findings board

In the crew the server runs in the same process, over in-memory streams: the protocol is the real
one, the transport has no network to fail. If the ``mcp`` package is missing or a call fails, the
tool runs directly instead and the bundle counts the fallback (``agents.mcp``). ``MATCHLENS_MCP=off``
turns the server off. The offline runner calls the tools directly.

The same server runs on stdio for any MCP client (VS Code, Claude Desktop, the MCP Inspector), over
a folder of generated matches:

    matchlens-mcp out/matches

There it adds tools to list the matches, read the momentum and the Watcher's moments, and open a
moment, which makes a board the other tools then work on, as the crew's agents do.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import itertools
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .crew import Job
    from .runners import ToolSpec

log = logging.getLogger(__name__)
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)  # one INFO line per tool call otherwise

MCP_VAR = "MATCHLENS_MCP"
CALL_TIMEOUT = 20.0  # seconds; a tool computes in milliseconds, so this only catches a stuck server

JOBS: dict[str, Job] = {}  # the moments being worked on, by job id: the boards the tools read and write
_ids = itertools.count(1)


def register(job: Job) -> str:
    key = f"{job.md.meta['match_id']}@{job.clock}#{next(_ids)}"
    JOBS[key] = job
    return key


def release(key: str) -> None:
    JOBS.pop(key, None)


def _job(key: str) -> Job:
    if key not in JOBS:
        raise ValueError(f"no open moment {key!r}")
    return JOBS[key]


def investigate(job: str, specialist: str) -> str:
    """One specialist's findings for a moment, computed from the match tables and posted to its board."""
    from .board import SPECIALISTS
    from .crew import specialist_tool

    if specialist not in SPECIALISTS:
        raise ValueError(f"specialist is one of {', '.join(SPECIALISTS)}")
    return specialist_tool(_job(job), specialist).fn()


def read_board(job: str) -> str:
    """A moment's findings board: the stats that could go on screen, the match context, each
    specialist's verdict, and the causes the evidence allows."""
    from .verifier import Verifier, cause_menu

    j = _job(job)
    if not j.menu:
        j.menu = cause_menu(j.md, j.m, j.board.by_agent())
        j.verifier = Verifier(j.md, j.m, j.board, j.menu)
    menu = [{k: v for k, v in o.items() if k in ("id", "kind", "team", "name", "meaning")} for o in j.menu]
    return json.dumps({"findings": j.board.view(), "verdicts": j.board.notes, "cause_menu": menu})


def check_card(job: str, cause: str, stats: list[str]) -> str:
    """Recompute a draft card's numbers and check it against the screen rules."""
    from .crew import check_tool

    j = _job(job)
    if j.verifier is None:
        read_board(job)  # builds the cause menu and the Verifier from what is on the board
    return check_tool(j).fn(cause, list(stats))


def server(matches: Path | None = None) -> Any:
    """The MCP server. With a folder of matches it can also open moments itself."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP(
        "matchlens",
        instructions="MatchLens: why momentum shifted in a football match. Open a moment, investigate it with the "
        "four specialists (team_play, players, substitutions, match_events), read the findings board, and check a card.",
    )
    for fn in (investigate, read_board, check_card):
        app.add_tool(fn, name=fn.__name__, description=inspect.getdoc(fn))
    if matches is not None:
        _add_match_tools(app, matches)
    return app


def _add_match_tools(app: Any, root: Path) -> None:
    from ..explain.match import MatchData, load
    from ..explain.watcher import momentum_series, watch
    from .crew import Job, describe

    loaded: dict[str, MatchData] = {}

    def match(match_id: str) -> MatchData:
        if match_id not in loaded:
            folder = root / match_id
            if not (folder / "match.json").exists() and not folder.is_dir():
                raise ValueError(f"no match {match_id!r} in {root}")
            loaded[match_id] = load(folder)
        return loaded[match_id]

    def list_matches() -> str:
        """The generated matches in this folder."""
        return json.dumps(sorted(p.name for p in root.iterdir() if p.is_dir()))

    def momentum(match_id: str) -> str:
        """The home side's share of final-third play, minute by minute, with the goals, cards and subs."""
        md = match(match_id)
        events = [
            {"kind": k.kind, "clock": k.clock, "team": k.team_id, "name": md.names.get(k.player_id or "", "")}
            for k in md.key_events
        ]
        return json.dumps({"teams": md.teams, "momentum": momentum_series(md), "events": events})

    def moments(match_id: str) -> str:
        """The moments the Watcher raises: when momentum shifted, and which side gained."""
        md = match(match_id)
        return json.dumps(
            [{"clock": md.clock_of(m.now - 1), "mode": m.mode, "gainer": m.gainer, "swing": round(m.swing, 1)} for m in watch(md)]
        )

    def open_moment(match_id: str, clock: str) -> str:
        """Open one of the Watcher's moments (clock as `moments` lists it). Returns the job id the
        other tools take, and what the agents are told about the moment."""
        md = match(match_id)
        for m in watch(md):
            if md.clock_of(m.now - 1) == clock:
                job = Job(md.until(m.now), m, clock)
                return json.dumps({"job": register(job), "moment": describe(job)})
        raise ValueError(f"no moment at {clock!r}; see moments({match_id!r})")

    for fn in (list_matches, momentum, moments, open_moment):
        app.add_tool(fn, name=fn.__name__, description=inspect.getdoc(fn))


class McpBridge:
    """The crew's connection to the server: runs it in-process and routes the agents' tool calls to it."""

    def __init__(self) -> None:
        self.calls = 0
        self.fallbacks = 0
        self.off = os.environ.get(MCP_VAR, "").lower() == "off"
        self._session: Any = None
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None
        self._lock: asyncio.Lock | None = None
        self._warned = False

    def as_dict(self) -> dict[str, Any]:
        return {"server": "matchlens", "calls": self.calls, "fallbacks": self.fallbacks}

    async def _serve(self, ready: asyncio.Event) -> None:
        try:
            from mcp.shared.memory import create_connected_server_and_client_session

            async with create_connected_server_and_client_session(server()) as session:
                self._session = session
                ready.set()
                assert self._stop is not None
                await self._stop.wait()
        except Exception as exc:  # no mcp package, or the server didn't start: tools run directly
            log.warning("MCP server not running (%s); the agents' tools run directly", exc)
        finally:
            self._session = None
            ready.set()

    async def start(self) -> bool:
        """Start the server once, in a task of its own, so whichever task asks first doesn't own it."""
        if self.off:
            return False
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._task is None:
                ready, self._stop = asyncio.Event(), asyncio.Event()
                self._task = asyncio.create_task(self._serve(ready), name="matchlens-mcp")
                await ready.wait()
        return self._session is not None

    async def call(self, name: str, args: dict[str, Any]) -> str:
        if not await self.start():
            raise RuntimeError("MCP server not running")
        result = await asyncio.wait_for(self._session.call_tool(name, args), CALL_TIMEOUT)
        text = "".join(getattr(c, "text", "") for c in result.content)
        if result.isError:
            raise RuntimeError(text or f"{name} failed")
        self.calls += 1
        return text

    def wrap(self, spec: ToolSpec) -> Callable[..., Any]:
        """The tool as the agent calls it: over MCP, or directly if the server can't answer."""
        if spec.via is None or self.off:
            return spec.fn
        name, hidden = spec.via

        async def over_mcp(**kwargs: Any) -> str:
            try:
                return await self.call(name, hidden | kwargs)
            except Exception as exc:
                if not self._warned:
                    log.warning("MCP call %s failed (%s); running the tool directly", name, exc)
                    self._warned = True
                self.fallbacks += 1
                return spec.fn(**kwargs)

        return over_mcp

    async def close(self) -> None:
        if self._task is not None and self._stop is not None:
            self._stop.set()
            try:
                await asyncio.wait_for(self._task, 5)
            except Exception:  # shutting down: nothing left to protect
                self._task.cancel()
            self._task = None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("matches", type=Path, help="a folder of generated matches (matchlens-gen output)")
    args = ap.parse_args()
    server(args.matches).run()  # stdio


if __name__ == "__main__":
    main()
