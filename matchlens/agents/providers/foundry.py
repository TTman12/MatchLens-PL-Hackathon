"""Microsoft Foundry provider: each task runs as a Microsoft Agent Framework agent.

Every agent role is published to the Foundry project's Agent Service as a prompt agent
(``matchlens-player``, ``matchlens-club`` and so on), and each lens, repair and
translation task runs as that agent through Microsoft Agent Framework. Agents get the
task's tools (Match-State lookups that add evidence) as function tools, so a Player
agent can fetch a season stat and cite it.

Settings come from environment variables only (see ``.env.example``):

- ``AZURE_AI_PROJECT_ENDPOINT``: the Foundry project endpoint,
  ``https://<resource>.services.ai.azure.com/api/projects/<project>``
- ``AZURE_AI_MODEL_FAST``: deployment for lens, verifier and translator agents
- ``AZURE_AI_MODEL_STRONG``: deployment for briefs and recaps (defaults to the fast one)

Authentication is Microsoft Entra ID through ``DefaultAzureCredential``: ``az login``
on a laptop, a managed identity in Azure Container Apps, or ``AZURE_CLIENT_ID``,
``AZURE_TENANT_ID`` and ``AZURE_CLIENT_SECRET`` for a service principal in CI. No key
is ever read from a file in the repository.

The SDKs are imported lazily, so the rest of MatchLens installs and runs without them.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .base import AgentTask, ProviderError

log = logging.getLogger(__name__)


class _ToolsDeclaredOnTheAgent(logging.Filter):
    """Drops Agent Framework's per-call note that a published agent's tool declarations
    come from its Foundry definition: that is how MatchLens publishes them."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "tool declarations cannot be sent" not in record.getMessage()


logging.getLogger("agent_framework.foundry").addFilter(_ToolsDeclaredOnTheAgent())

ENDPOINT_VAR = "AZURE_AI_PROJECT_ENDPOINT"
FAST_VAR = "AZURE_AI_MODEL_FAST"
STRONG_VAR = "AZURE_AI_MODEL_STRONG"


@dataclass(frozen=True)
class FoundrySettings:
    endpoint: str
    fast_model: str
    strong_model: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> FoundrySettings:
        env = os.environ if env is None else env
        endpoint = env.get(ENDPOINT_VAR, "").strip()
        fast = env.get(FAST_VAR, "").strip()
        if not endpoint or not fast:
            raise ProviderError(f"Foundry provider needs {ENDPOINT_VAR} and {FAST_VAR} to be set")
        return cls(
            endpoint=endpoint, fast_model=fast, strong_model=env.get(STRONG_VAR, "").strip() or fast
        )


class AgentFrameworkProvider:
    """Runs each task as an Agent Framework ``Agent`` on the chat client for its tier.

    Any Agent Framework chat client works; ``FoundryProvider`` supplies Foundry ones.
    Tests pass a scripted client to exercise the real ``Agent`` path offline.
    """

    name = "agent-framework"

    def __init__(self, clients: Mapping[str, Any]) -> None:
        self._clients = dict(clients)

    def _local_agent(self, task: AgentTask, name: str | None = None) -> Any:
        from agent_framework import Agent

        return Agent(
            client=self._clients[task.tier],
            instructions=task.instructions,
            name=name or task.instance.replace(":", "_"),
            tools=list(task.tools) or None,
        )

    async def _agent(self, task: AgentTask) -> Any:
        return self._local_agent(task)

    async def complete(self, task: AgentTask) -> str:
        agent = await self._agent(task)
        try:
            response = await agent.run(task.prompt)
        except Exception as exc:  # the SDK raises many types; all mean "no answer"
            raise ProviderError(f"{task.instance}: {type(exc).__name__}: {exc}") from exc
        text = response.text or ""
        if not text.strip():
            raise ProviderError(f"{task.instance}: empty reply")
        return text


AGENT_DESCRIPTIONS = {
    "player": "MatchLens Player lens: a fan's fact box on one player's part in a moment.",
    "club": "MatchLens Club lens: a partisan fact box for one club's fans.",
    "pundit": "MatchLens Pundit lens: the analyst's read of a moment.",
    "verifier": "MatchLens Verifier: repairs a box whose numbers the evidence does not back.",
    "translator": "MatchLens Translator: localises an approved box with numbers and names locked.",
}


def foundry_agent_name(task: AgentTask) -> str:
    """The Foundry agent a task runs as: one per role, and one for the half-time briefs."""
    return f"matchlens-{task.agent}" + ("-brief" if task.tier == "strong" else "")


class FoundryProvider(AgentFrameworkProvider):
    """Runs each task as a prompt agent registered in the Foundry project.

    Every agent role (Player, Club, Pundit, Verifier, Translator, and the Pundit's
    briefs) is published to the project's Agent Service once, as ``matchlens-<role>``,
    so it is listed on the portal's Agents page with its model, instructions and tool
    declarations. A new version is published only when the definition changes. Tasks
    then run as that agent; its Match-State tools execute here, in the pipeline.

    If an agent cannot be published (for example, the identity may call models but not
    manage agents), its tasks run on the model deployment directly instead.
    """

    name = "foundry"

    def __init__(self, settings: FoundrySettings, credential: Any | None = None) -> None:
        self.settings = settings
        try:
            from agent_framework_foundry import FoundryChatClient
            from azure.ai.projects.aio import AIProjectClient
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as exc:  # pragma: no cover - depends on optional extras
            raise ProviderError(
                "Foundry provider needs the 'foundry' extra: pip install -e '.[foundry]'"
            ) from exc
        self._credential = credential or DefaultAzureCredential()
        self._project = AIProjectClient(endpoint=settings.endpoint, credential=self._credential)
        super().__init__(
            {
                tier: FoundryChatClient(project_client=self._project, model=model)
                for tier, model in (
                    ("fast", settings.fast_model),
                    ("strong", settings.strong_model),
                )
            }
        )
        self.versions: dict[str, str | None] = {}
        """Published version per Foundry agent name; None if it could not be published."""
        self._publishing = asyncio.Lock()

    async def _agent(self, task: AgentTask) -> Any:
        from agent_framework_foundry import FoundryAgent

        name = foundry_agent_name(task)
        version = await self._published(name, task)
        if version is None:
            return self._local_agent(task, name)
        return FoundryAgent(
            project_client=self._project,
            agent_name=name,
            agent_version=version,
            tools=list(task.tools) or None,
        )

    async def publish(self, tasks: list[AgentTask]) -> dict[str, str | None]:
        """Publish the Foundry agent for each task now, rather than on its first call."""
        for task in tasks:
            await self._published(foundry_agent_name(task), task)
        return dict(self.versions)

    async def _published(self, name: str, task: AgentTask) -> str | None:
        async with self._publishing:
            if name in self.versions:
                return self.versions[name]
            try:
                version = await self._publish(name, task)
            except Exception:  # never let the portal listing stop the match
                log.warning("could not publish Foundry agent %s; calling the model directly", name)
                log.debug("publish failure", exc_info=True)
                version = None
            self.versions[name] = version
            return version

    async def _publish(self, name: str, task: AgentTask) -> str:
        """The latest version of ``name`` if it matches this definition, else a new one."""
        from azure.core.exceptions import ResourceNotFoundError

        definition = prompt_agent_definition(self._local_agent(task, name))
        digest = hashlib.sha256(
            json.dumps(definition.as_dict(), sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        try:
            latest = (await self._project.agents.get(agent_name=name)).versions["latest"]
            if (latest.get("metadata") or {}).get("definition") == digest:
                return str(latest["version"])
        except ResourceNotFoundError:
            pass
        created = await self._project.agents.create_version(
            agent_name=name,
            definition=definition,
            description=AGENT_DESCRIPTIONS.get(task.agent, "MatchLens agent"),
            metadata={"definition": digest},
        )
        log.info("published Foundry agent %s version %s", name, created.version)
        return str(created.version)

    async def close(self) -> None:
        await self._project.close()
        close = getattr(self._credential, "close", None)
        if close is not None:
            await close()


def prompt_agent_definition(agent: Any) -> Any:
    """The Foundry ``PromptAgentDefinition`` for an Agent Framework agent.

    Foundry checks function tools strictly, so every tool's parameters must say that no
    other properties are allowed.
    """
    import inspect
    import warnings

    from agent_framework_foundry import to_prompt_agent

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # to_prompt_agent is marked experimental
        definition = to_prompt_agent(agent)
    for tool in definition.get("tools") or []:
        if tool.get("type") == "function":
            tool["parameters"]["additionalProperties"] = False
            # Python 3.13 dedents docstrings and 3.12 does not; publish the same text from both.
            tool["description"] = inspect.cleandoc(tool.get("description") or "")
    return definition


def configure_tracing(env: Mapping[str, str] | None = None) -> bool:
    """Send Agent Framework traces to Application Insights, which Foundry tracing reads.

    Does nothing unless ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set. Returns whether
    tracing was turned on.
    """
    env = os.environ if env is None else env
    connection = env.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection:
        return False
    try:
        from agent_framework.observability import enable_instrumentation
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:  # pragma: no cover - optional extra
        return False
    # Export spans from every library, but log records only from MatchLens itself: the
    # Azure SDK logs every HTTP request, and the exporter logs every export.
    configure_azure_monitor(connection_string=connection, logger_name="matchlens")
    enable_instrumentation()
    return True
