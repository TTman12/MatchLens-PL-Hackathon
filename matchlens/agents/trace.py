"""The agent timeline behind the "Under the hood" drawer.

Every agent step records what it did to which moment: drafted, retried, timed out,
fell back to a template, was rejected or repaired by the Verifier, was cut for budget
by the Director. The pipeline writes the timeline to ``agent_trace.json`` next to the
moments and cues.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TraceEvent:
    seq: int
    moment_id: str | None
    agent: str
    instance: str
    action: str
    status: str
    """``ok``, ``retry``, ``timeout``, ``error``, ``degraded``, ``repaired``, ``fallback``,
    ``rejected``, ``cut`` or ``skipped``."""
    detail: str = ""
    elapsed_ms: float = 0.0


@dataclass
class AgentTrace:
    provider: str = ""
    events: list[TraceEvent] = field(default_factory=list)

    def add(
        self,
        moment_id: str | None,
        agent: str,
        instance: str,
        action: str,
        status: str = "ok",
        detail: str = "",
        started: float | None = None,
    ) -> TraceEvent:
        elapsed = (time.perf_counter() - started) * 1000 if started is not None else 0.0
        event = TraceEvent(
            len(self.events) + 1,
            moment_id,
            agent,
            instance,
            action,
            status,
            detail,
            round(elapsed, 1),
        )
        self.events.append(event)
        return event

    def for_moment(self, moment_id: str) -> list[TraceEvent]:
        return [e for e in self.events if e.moment_id == moment_id]

    def statuses(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.events:
            counts[e.status] = counts.get(e.status, 0) + 1
        return counts

    def degraded_agents(self) -> list[str]:
        return sorted({e.instance for e in self.events if e.status in ("timeout", "error")})

    def to_json(self) -> dict[str, Any]:
        # Timings vary run to run; keep the file stable so it can be diffed and cached.
        return {
            "provider": self.provider,
            "summary": self.statuses(),
            "degraded": self.degraded_agents(),
            "events": [asdict(e) | {"elapsed_ms": None} for e in self.events],
        }

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")
