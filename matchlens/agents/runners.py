"""Where the agents' reasoning runs: on Microsoft Foundry, or offline.

- ``FoundryRunner`` publishes each role to the Foundry project's Agent Service as a prompt agent
  (``matchlens-team-play``, ..., ``matchlens-explainer``), with its instructions, model and tool
  declarations, and runs each task as that agent through Microsoft Agent Framework. The tools run
  here, in the pipeline, on the match tables.
- ``OfflineRunner`` stands in for the models with the deterministic rules in matchlens/explain, so
  the whole crew runs in CI and with no Azure account. It makes the same tool calls.

Foundry settings come from the environment: ``AZURE_AI_PROJECT_ENDPOINT`` and
``AZURE_AI_MODEL`` (default ``gpt-4.1-mini``). Authentication is Microsoft Entra ID through
``DefaultAzureCredential`` (``az login`` on a laptop, a managed identity in Azure). The SDKs are
imported lazily, so the rest of MatchLens installs and runs without them. Each Foundry run is
traced to the project's Application Insights (see matchlens/telemetry.py).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from .. import telemetry
from .roles import Role

if TYPE_CHECKING:
    from .analyst import AnalystJob
    from .crew import Job
    from .interpreter import InterpretJob

log = logging.getLogger(__name__)


class _ToolsDeclaredOnTheAgent(logging.Filter):
    """Drops Agent Framework's per-call note that a published agent's tools come from its Foundry
    definition: that is how they are published here."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "tool declarations cannot be sent" not in record.getMessage()


logging.getLogger("agent_framework.foundry").addFilter(_ToolsDeclaredOnTheAgent())

ENDPOINT_VAR = "AZURE_AI_PROJECT_ENDPOINT"
MODEL_VAR = "AZURE_AI_MODEL"
DEFAULT_MODEL = "gpt-4.1-mini"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    fn: Callable[..., str]


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0

    def add(self, details: Any, seconds: float) -> None:
        self.calls += 1
        self.seconds += seconds
        if isinstance(details, dict):
            self.input_tokens += int(details.get("input_token_count") or 0)
            self.output_tokens += int(details.get("output_token_count") or 0)

    def as_dict(self) -> dict[str, Any]:
        return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


class RunnerError(RuntimeError):
    pass


class Runner(Protocol):
    name: str
    usage: Usage

    async def run(self, role: Role, prompt: str, tools: list[ToolSpec], job: Job | InterpretJob | AnalystJob) -> str: ...

    async def close(self) -> None: ...


@dataclass
class OfflineRunner:
    """The deterministic stand-in. Its answers are what matchlens/explain would decide."""

    name: str = "offline"
    usage: Usage = field(default_factory=Usage)

    async def run(self, role: Role, prompt: str, tools: list[ToolSpec], job: Job | InterpretJob | AnalystJob) -> str:
        from .analyst import AnalystJob, offline_analysis
        from .crew import offline_answer
        from .interpreter import InterpretJob, offline_lines

        self.usage.calls += 1
        if isinstance(job, InterpretJob):
            return offline_lines(job)
        if isinstance(job, AnalystJob):
            return offline_analysis(job)
        return offline_answer(role, tools, job)

    async def close(self) -> None:
        return None


class FoundryRunner:
    """Runs each task as a prompt agent published in the Foundry project."""

    name = "foundry"

    def __init__(self, endpoint: str | None = None, model: str | None = None, concurrency: int = 6, timeout: float = 90) -> None:
        try:
            from agent_framework_foundry import FoundryChatClient
            from azure.ai.projects.aio import AIProjectClient
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as exc:  # pragma: no cover - depends on optional extras
            raise RunnerError("the Foundry runner needs the 'foundry' extra: pip install -e '.[foundry]'") from exc
        endpoint = endpoint or os.environ.get(ENDPOINT_VAR, "").strip()
        if not endpoint:
            raise RunnerError(f"set {ENDPOINT_VAR} to the Foundry project endpoint")
        self.model = model or os.environ.get(MODEL_VAR, "").strip() or DEFAULT_MODEL
        self._credential = DefaultAzureCredential()
        self._project = AIProjectClient(endpoint=endpoint, credential=self._credential)
        self._client = FoundryChatClient(project_client=self._project, model=self.model)
        self._slots = asyncio.Semaphore(concurrency)
        self._publishing = asyncio.Lock()
        self.timeout = timeout
        self.versions: dict[str, str | None] = {}
        self.usage = Usage()
        self.tracing: bool | None = None  # decided on the first task

    def _tools(self, tools: list[ToolSpec]) -> list[Any]:
        from agent_framework import tool

        return [tool(t.fn, name=t.name, description=t.description) for t in tools]

    def _local(self, role: Role, tools: list[ToolSpec]) -> Any:
        from agent_framework import Agent

        return Agent(client=self._client, instructions=role.instructions, name=role.agent_name, tools=self._tools(tools) or None)

    async def _agent(self, role: Role, tools: list[ToolSpec]) -> Any:
        from agent_framework_foundry import FoundryAgent

        version = await self._published(role, tools)
        if version is None:
            return self._local(role, tools)
        return FoundryAgent(
            project_client=self._project, agent_name=role.agent_name, agent_version=version, tools=self._tools(tools) or None
        )

    async def run(self, role: Role, prompt: str, tools: list[ToolSpec], job: Job | InterpretJob | AnalystJob) -> str:
        if self.tracing is None:
            self.tracing = await telemetry.connect(self._project)
        agent = await self._agent(role, tools)
        last: Exception | None = None
        for attempt in range(3):
            async with self._slots:
                t0 = time.monotonic()
                try:
                    response = await asyncio.wait_for(agent.run(prompt), self.timeout)
                except Exception as exc:  # the SDK raises many types; all mean "no answer this time"
                    last = exc
                    log.info("%s attempt %d failed: %s", role.agent_name, attempt + 1, exc)
                else:
                    self.usage.add(getattr(response, "usage_details", None), time.monotonic() - t0)
                    text = response.text or ""
                    if text.strip():
                        return str(text)
                    last = RunnerError("empty reply")
            await asyncio.sleep(4 ** (attempt + 1))  # rate limits clear in seconds, not milliseconds
        raise RunnerError(f"{role.agent_name}: {type(last).__name__}: {last}")

    async def publish(self, roles: list[tuple[Role, list[ToolSpec]]]) -> dict[str, str | None]:
        for role, tools in roles:
            await self._published(role, tools)
        return dict(self.versions)

    async def _published(self, role: Role, tools: list[ToolSpec]) -> str | None:
        async with self._publishing:
            if role.agent_name not in self.versions:
                try:
                    self.versions[role.agent_name] = await self._publish(role, tools)
                except Exception:  # never let the portal listing stop the match
                    log.warning("could not publish %s; calling the model directly", role.agent_name, exc_info=True)
                    self.versions[role.agent_name] = None
            return self.versions[role.agent_name]

    async def _publish(self, role: Role, tools: list[ToolSpec]) -> str:
        """The latest version of the agent if it matches this definition, else a new version."""
        import warnings

        from agent_framework_foundry import to_prompt_agent
        from azure.core.exceptions import ResourceNotFoundError

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # to_prompt_agent is marked experimental
            definition = to_prompt_agent(self._local(role, tools))
        for t in definition.get("tools") or []:
            if t.get("type") == "function":  # Foundry checks function tools strictly
                t["parameters"]["additionalProperties"] = False
        digest = hashlib.sha256(json.dumps(definition.as_dict(), sort_keys=True, default=str).encode()).hexdigest()[:16]
        try:
            latest = (await self._project.agents.get(agent_name=role.agent_name)).versions["latest"]
            if (latest.get("metadata") or {}).get("definition") == digest:
                return str(latest["version"])
        except ResourceNotFoundError:
            pass
        created = await self._project.agents.create_version(
            agent_name=role.agent_name, definition=definition, description=role.description, metadata={"definition": digest}
        )
        log.info("published Foundry agent %s version %s", role.agent_name, created.version)
        return str(created.version)

    async def close(self) -> None:
        telemetry.flush()
        await self._project.close()
        await self._credential.close()


def make_runner(name: str) -> Runner:
    if name == "offline":
        return OfflineRunner()
    if name == "foundry":
        return FoundryRunner()
    raise RunnerError(f"unknown runner {name!r}: offline or foundry")
