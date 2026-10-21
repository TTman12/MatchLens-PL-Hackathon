"""Failover for a generated match's agents, and the fault drill that shows it on screen.

Every agent call in a generated match goes through ``FailoverRunner``. When an agent fails, the
call is tried once more; if that fails too, the call is handed to a stand-in that answers the same
task with the deterministic rules (``OfflineRunner``). The rest of the chain carries on as usual:
the stand-in's specialist findings go on the board beside the other specialists', a stand-in
Explainer's draft still goes through the Verifier, and a stand-in Interpreter's or Analyst's lines
still go through their checks in code. Each failure is written down as an incident and ends up on
the card it happened to, so the screen can say which agent failed, what was retried, who stood in
and which check the result passed.

The fault drill makes a failure happen on purpose: one chosen agent fails every call for the whole
match (``down``), or fails only its first try at each task (``flaky``), so the retry answers. The
fault is injected here, before the call leaves the server, so a drill costs no model calls and can't
reach any other viewer's match. It is asked for from the admin screen (``POST /api/generate?drill=``,
see server.py).
"""

from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..agents.roles import Role
from ..agents.runners import Runner, RunnerError, ToolSpec

if TYPE_CHECKING:
    from ..agents.runners import AnyJob

# what the drill may knock out: the agents that work on each card
DRILL_AGENTS = ("team_play", "players", "substitutions", "match_events", "explainer", "interpreter", "analyst")
DRILL_MODES = ("down", "flaky")
RETRIES = 1  # tries after the first, before the stand-in takes the task
RETRY_DELAY = 0.25  # seconds before the retry

_incidents: ContextVar[list[dict[str, Any]] | None] = ContextVar("matchlens_incidents", default=None)


def recording() -> list[dict[str, Any]]:
    """Start a fresh incident log for the current task (one card's work) and return it."""
    log: list[dict[str, Any]] = []
    _incidents.set(log)
    return log


class InjectedFault(RunnerError):
    pass


@dataclass(frozen=True)
class Drill:
    agent: str
    mode: str = "down"

    @classmethod
    def parse(cls, agent: str | None, mode: str | None = None) -> Drill | None:
        """A drill from request parameters, or None. Raises ValueError on an unknown agent or mode."""
        if not agent:
            return None
        if agent not in DRILL_AGENTS:
            raise ValueError(f"unknown agent {agent!r}: one of {', '.join(DRILL_AGENTS)}")
        mode = mode or "down"
        if mode not in DRILL_MODES:
            raise ValueError(f"unknown mode {mode!r}: down or flaky")
        return cls(agent, mode)

    def hits(self, role: Role, attempt: int) -> bool:
        return role.key == self.agent and (self.mode == "down" or attempt == 0)

    def as_dict(self) -> dict[str, str]:
        return {"agent": self.agent, "mode": self.mode}


class FailoverRunner:
    """`primary` (Foundry, or the rules when the agents are off) with a retry and a rules stand-in."""

    def __init__(self, primary: Runner, standby: Runner, drill: Drill | None = None) -> None:
        self.primary = primary
        self.standby = standby
        self.drill = drill
        self.incidents = 0
        self.name = primary.name
        self.usage = primary.usage  # the same counter: the budget books the primary's calls

    def __getattr__(self, attr: str) -> Any:  # versions, safety, the credential: the primary's
        return getattr(self.primary, attr)

    async def run(self, role: Role, prompt: str, tools: list[ToolSpec], job: AnyJob) -> str:
        tries: list[dict[str, Any]] = []
        for attempt in range(1 + RETRIES):
            t0 = time.monotonic()
            try:
                if self.drill and self.drill.hits(role, attempt):
                    raise InjectedFault(f"{role.agent_name}: fault drill, call stopped before it left the server")
                text = await self.primary.run(role, prompt, tools, job)
            except Exception as exc:  # whatever the SDK raised: this agent gave no answer
                drilled = isinstance(exc, InjectedFault)
                tries.append({"try": attempt + 1, "status": "failed", "drill": drilled, "error": str(exc)[:160], "ms": _ms(t0)})
                if not drilled:  # a real failure has already had the runner's own retries
                    break
                await asyncio.sleep(RETRY_DELAY)
                continue
            if tries:
                tries.append({"try": attempt + 1, "status": "answered", "ms": _ms(t0)})
                self._note(role, tries, "retry")
            return text
        self._note(role, tries, "standby")
        t0 = time.monotonic()
        text = await self.standby.run(role, prompt, tools, job)
        tries.append({"try": "stand-in", "status": "answered", "ms": _ms(t0)})
        return text

    def _note(self, role: Role, tries: list[dict[str, Any]], recovered_by: str) -> None:
        self.incidents += 1
        log = _incidents.get()
        if log is not None:
            drill = any(t.get("drill") for t in tries)
            log.append({"agent": role.key, "drill": drill, "recovered_by": recovered_by, "tries": tries})

    async def close(self) -> None:
        await self.primary.close()


def _ms(t0: float) -> int:
    return round(1000 * (time.monotonic() - t0))
