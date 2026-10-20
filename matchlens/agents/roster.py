"""The agent roster: one task per agent the pipeline runs, without a moment.

Each entry carries the same role, tier, instructions and tool declarations as the
pipeline's real tasks for that agent, so a provider can register every agent up front
(Foundry Agent Service lists them before the first match is played) and the real tasks
then find a matching definition.
"""

from __future__ import annotations

from typing import Any

from .lenses import EvidenceTools, prompt
from .providers import AgentTask


def agent_roster() -> list[AgentTask]:
    # The tools only read the moment when called; their declarations need neither.
    tools = EvidenceTools(None, None).functions()  # type: ignore[arg-type]

    def task(agent: Any, tier: Any = "fast", with_tools: bool = False) -> AgentTask:
        return AgentTask(
            agent=agent,
            instance=f"{agent}-agent",
            instructions=prompt(agent),
            prompt="",
            tier=tier,
            tools=list(tools) if with_tools else [],
        )

    return [
        task("player", with_tools=True),
        task("club", with_tools=True),
        task("pundit", with_tools=True),
        task("pundit", tier="strong"),  # the half-time and full-time briefs
        task("verifier"),
        task("translator"),
    ]


async def publish_agents(provider: Any) -> dict[str, str | None]:
    """Register every agent with the provider (or the provider it wraps) if it can."""
    while provider is not None and not hasattr(provider, "publish"):
        provider = getattr(provider, "inner", None)
    if provider is None:
        return {}
    result: dict[str, str | None] = await provider.publish(agent_roster())
    return result
