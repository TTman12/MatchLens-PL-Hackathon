"""Fault injection: kill an agent, or make it state a wrong number.

Used by the demo's chaos toggle (kill the Pundit mid-match and watch the template
fallback take over) and by the tests and evals that prove the Verifier stops a wrong
figure from reaching a cue.

Rules are matched against the task's agent role or instance, e.g. ``pundit`` or
``player-agent:ash-09``:

- ``kill:<pattern>`` raises ``ProviderError`` as a timed-out or crashed agent would;
- ``misquote:<pattern>`` lets the inner provider answer, then changes the first number
  in its headline or body, the way a model misremembers a figure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .base import AgentTask, ModelProvider, ProviderError

_FIRST_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _corrupt(text: str) -> str:
    def bump(m: re.Match[str]) -> str:
        raw = m.group(0)
        if "." in raw:
            return f"{float(raw) + 1.7:.1f}"
        return str(int(raw) + 3)

    return _FIRST_NUMBER.sub(bump, text, count=1)


@dataclass
class ChaosProvider:
    inner: ModelProvider
    kill: set[str] = field(default_factory=set)
    misquote: set[str] = field(default_factory=set)
    name: str = "chaos"
    corrupted: list[str] = field(default_factory=list)
    """Instances whose reply was actually changed (a reply with no number cannot be)."""

    @classmethod
    def from_rules(cls, inner: ModelProvider, rules: list[str]) -> ChaosProvider:
        kill = {r.split(":", 1)[1] for r in rules if r.startswith("kill:")}
        misquote = {r.split(":", 1)[1] for r in rules if r.startswith("misquote:")}
        unknown = [r for r in rules if not r.startswith(("kill:", "misquote:"))]
        if unknown:
            raise ValueError(f"unknown chaos rules {unknown}; use kill:<agent> or misquote:<agent>")
        return cls(inner=inner, kill=kill, misquote=misquote, name=f"chaos({inner.name})")

    @staticmethod
    def _hits(patterns: set[str], task: AgentTask) -> bool:
        return task.agent in patterns or task.instance in patterns or "*" in patterns

    async def complete(self, task: AgentTask) -> str:
        if self._hits(self.kill, task):
            raise ProviderError(f"{task.instance} killed by chaos toggle")
        reply = await self.inner.complete(task)
        if task.agent in ("player", "club", "pundit") and self._hits(self.misquote, task):
            data = json.loads(reply)
            before = (data.get("headline", ""), data.get("body", ""))
            if _FIRST_NUMBER.search(data.get("headline", "")):
                data["headline"] = _corrupt(data["headline"])
            else:
                data["body"] = _corrupt(data.get("body", ""))
            if (data.get("headline", ""), data.get("body", "")) != before:
                data.pop("template", None)  # the corrupted text is no longer the template's
                self.corrupted.append(task.instance)
            reply = json.dumps(data)
        return reply
