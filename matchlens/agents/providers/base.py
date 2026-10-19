"""The model provider interface every agent calls through.

An agent never talks to a model SDK directly. It builds an ``AgentTask`` (instructions,
a prompt, and the same input as structured data) and hands it to a ``ModelProvider``,
which returns the model's reply as text. That keeps three things swappable:

- ``FoundryProvider`` runs each task as a Microsoft Agent Framework ``Agent`` on a
  Microsoft Foundry model deployment;
- ``OfflineProvider`` answers deterministically from the structured input, so tests,
  CI and the demo run with no credentials;
- ``ChaosProvider`` wraps either one to kill or corrupt chosen agents, to show failure
  recovery and to test that the Verifier catches a wrong number.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Tier = Literal["fast", "strong"]


class ProviderError(RuntimeError):
    """The provider could not produce an answer. Callers retry once, then fall back."""


@dataclass
class AgentTask:
    agent: str
    """Agent role: ``player``, ``club``, ``pundit``, ``verifier`` or ``translator``."""
    instance: str
    """This instance, e.g. ``player-agent:ash-09``. Shown in the agent timeline."""
    instructions: str
    """System instructions, from ``matchlens/agents/prompts``."""
    prompt: str
    """The user message: the moment's facts and evidence, as JSON."""
    payload: dict[str, Any] = field(default_factory=dict)
    """The same input as Python objects, for providers that do not need a model."""
    tier: Tier = "fast"
    tools: list[Callable[..., Any]] = field(default_factory=list)
    """Functions the agent may call, e.g. Match-State lookups that add evidence."""


class ModelProvider(Protocol):
    name: str

    async def complete(self, task: AgentTask) -> str:
        """Run the task and return the reply text (JSON for every MatchLens agent)."""
        ...
