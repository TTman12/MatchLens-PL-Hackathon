"""Microsoft Foundry provider: each task runs as a Microsoft Agent Framework agent.

Every lens, repair and translation task becomes an ``agent_framework.Agent`` backed by
a ``FoundryChatClient`` on a model deployment in a Foundry project. Agents get the
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

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .base import AgentTask, ProviderError

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

    async def complete(self, task: AgentTask) -> str:
        from agent_framework import Agent

        agent = Agent(
            client=self._clients[task.tier],
            instructions=task.instructions,
            name=task.instance.replace(":", "_"),
            tools=list(task.tools) or None,
        )
        try:
            response = await agent.run(task.prompt)
        except Exception as exc:  # the SDK raises many types; all mean "no answer"
            raise ProviderError(f"{task.instance}: {type(exc).__name__}: {exc}") from exc
        text = response.text or ""
        if not text.strip():
            raise ProviderError(f"{task.instance}: empty reply")
        return text


class FoundryProvider(AgentFrameworkProvider):
    name = "foundry"

    def __init__(self, settings: FoundrySettings, credential: Any | None = None) -> None:
        self.settings = settings
        try:
            from agent_framework_foundry import FoundryChatClient
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as exc:  # pragma: no cover - depends on optional extras
            raise ProviderError(
                "Foundry provider needs the 'foundry' extra: pip install -e '.[foundry]'"
            ) from exc
        self._credential = credential or DefaultAzureCredential()
        super().__init__(
            {
                tier: FoundryChatClient(
                    project_endpoint=settings.endpoint, model=model, credential=self._credential
                )
                for tier, model in (
                    ("fast", settings.fast_model),
                    ("strong", settings.strong_model),
                )
            }
        )

    async def close(self) -> None:
        close = getattr(self._credential, "close", None)
        if close is not None:
            await close()


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
    configure_azure_monitor(connection_string=connection)
    enable_instrumentation()
    return True
