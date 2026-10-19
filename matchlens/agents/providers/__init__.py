"""Model providers: Microsoft Foundry via Agent Framework, deterministic offline, and chaos."""

from __future__ import annotations

import os
from collections.abc import Mapping

from .base import AgentTask, ModelProvider, ProviderError, Tier
from .chaos import ChaosProvider
from .foundry import (
    ENDPOINT_VAR,
    AgentFrameworkProvider,
    FoundryProvider,
    FoundrySettings,
    configure_tracing,
)
from .offline import OfflineProvider

PROVIDER_VAR = "MATCHLENS_PROVIDER"


def provider_from_env(
    env: Mapping[str, str] | None = None, *, chaos: list[str] | None = None
) -> ModelProvider:
    """Pick the provider: ``MATCHLENS_PROVIDER`` if set, else Foundry when it is configured.

    With nothing configured this returns the offline provider, so a fresh clone runs.
    """
    env = os.environ if env is None else env
    choice = env.get(PROVIDER_VAR, "").strip().lower()
    if not choice:
        choice = "foundry" if env.get(ENDPOINT_VAR, "").strip() else "offline"
    provider: ModelProvider
    if choice == "offline":
        provider = OfflineProvider()
    elif choice == "foundry":
        provider = FoundryProvider(FoundrySettings.from_env(env))
    else:
        raise ProviderError(f"{PROVIDER_VAR} must be 'offline' or 'foundry', not {choice!r}")
    if chaos:
        provider = ChaosProvider.from_rules(provider, chaos)
    return provider


__all__ = [
    "AgentFrameworkProvider",
    "AgentTask",
    "ChaosProvider",
    "FoundryProvider",
    "FoundrySettings",
    "ModelProvider",
    "OfflineProvider",
    "ProviderError",
    "Tier",
    "configure_tracing",
    "provider_from_env",
]
