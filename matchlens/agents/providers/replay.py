"""Replay: answer a repeated agent task from memory, and cap what a public link spends.

Replaying a match asks the agents the same tasks again: the same moments, the same
evidence, the same prompts. ``ReplayProvider`` remembers each answer together with the
Match-State lookups the agent made on the way. A repeated task re-runs those lookups,
so their evidence is on the moment again for the Verifier, and returns the remembered
text. Only new tasks reach the model, so a looping live match pays once.

``daily_budget`` caps how many tasks a day (UTC) may reach the model. Past it, a task
with no remembered answer gets the fallback's answer (the offline templates), so a
public demo link has a bounded worst-case cost and never goes silent.

With a ``store``, the remembered answers and today's count survive a restart, which
matters on Azure Container Apps: the app scales to zero between viewers.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from .base import AgentTask, ModelProvider
from .offline import OfflineProvider

log = logging.getLogger(__name__)

Call = tuple[str, dict[str, Any]]


class ReplayStore(Protocol):
    """Somewhere to keep the replay state between restarts, as one JSON document."""

    async def load(self) -> dict[str, Any] | None: ...

    async def save(self, state: dict[str, Any]) -> None: ...


@dataclass
class ReplayProvider:
    inner: ModelProvider
    daily_budget: int | None = None
    store: ReplayStore | None = None
    fallback: ModelProvider = field(default_factory=OfflineProvider)
    clock: Callable[[], float] = time.time
    save_delay_s: float = 5.0
    name: str = ""
    model_calls: int = 0
    replayed: int = 0
    over_budget: int = 0
    _answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    _day: int = -1
    _spent_today: int = 0
    _loaded: bool = False
    _save_task: asyncio.Task[None] | None = None

    def __post_init__(self) -> None:
        self.name = self.name or f"replay({self.inner.name})"

    async def complete(self, task: AgentTask) -> str:
        await self._load()
        key = hashlib.sha256(
            "\0".join((task.agent, task.instance, task.instructions, task.prompt)).encode()
        ).hexdigest()
        answer = self._answers.get(key)
        if answer is not None:
            tools = {f.__name__: f for f in task.tools}
            for name, kwargs in answer["calls"]:
                tools[name](**kwargs)
            self.replayed += 1
            return str(answer["text"])
        if not self._spend():
            self.over_budget += 1
            return await self.fallback.complete(task)
        calls: list[Call] = []
        text = await self.inner.complete(
            replace(task, tools=[_recorded(f, calls) for f in task.tools])
        )
        self._answers[key] = {"text": text, "calls": calls}
        self._schedule_save()
        return text

    def usage(self) -> dict[str, Any]:
        """What this provider has done, for a health check: calls, replays, today's budget."""
        return {
            "provider": self.name,
            "model_calls": self.model_calls,
            "replayed": self.replayed,
            "over_budget": self.over_budget,
            "spent_today": self._spent_today if self._day == int(self.clock() // 86400) else 0,
            "daily_budget": self.daily_budget,
            "remembered": len(self._answers),
            "state_loaded": self._loaded,
            "foundry_agents": dict(getattr(self.inner, "versions", {})),
        }

    def _spend(self) -> bool:
        """Count one model call against today's budget; False if none is left."""
        day = int(self.clock() // 86400)
        if day != self._day:
            self._day, self._spent_today = day, 0
        if self.daily_budget is not None and self._spent_today >= self.daily_budget:
            return False
        self._spent_today += 1
        self.model_calls += 1
        return True

    async def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self.store is None:
            return
        try:
            state = await self.store.load()
        except Exception:  # a missing or broken store must not stop the match
            log.exception("could not load replay state; starting empty")
            return
        if state:
            self._answers = state.get("answers", {}) | self._answers
            if state.get("day") == int(self.clock() // 86400):
                self._day, self._spent_today = state["day"], int(state.get("spent", 0))

    def _schedule_save(self) -> None:
        if self.store is not None and (self._save_task is None or self._save_task.done()):
            self._save_task = asyncio.create_task(self._save_soon())

    async def _save_soon(self) -> None:
        await asyncio.sleep(self.save_delay_s)  # one write for a burst of answers
        await self.flush()

    async def flush(self) -> None:
        """Write the replay state now."""
        if self.store is None:
            return
        state = {"day": self._day, "spent": self._spent_today, "answers": self._answers}
        try:
            await self.store.save(json.loads(json.dumps(state)))
        except Exception:
            log.exception("could not save replay state")

    async def close(self) -> None:
        if self._save_task is not None and not self._save_task.done():
            self._save_task.cancel()
        await self.flush()


def _recorded(fn: Callable[..., Any], calls: list[Call]) -> Callable[..., Any]:
    """``fn`` with the same name, signature and docstring, logging each call's arguments."""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        calls.append((fn.__name__, dict(signature.bind(*args, **kwargs).arguments)))
        return fn(*args, **kwargs)

    return wrapper


class BlobReplayStore:
    """The replay state as one JSON blob in Azure Storage, reached with Entra ID.

    ``url`` is the blob's full URL, e.g.
    ``https://<account>.blob.core.windows.net/replay/m291.json``.
    """

    def __init__(self, url: str) -> None:
        self.url = url

    def _client(self, credential: Any) -> Any:
        from azure.storage.blob.aio import BlobClient

        return BlobClient.from_blob_url(self.url, credential=credential)

    async def load(self) -> dict[str, Any] | None:
        from azure.core.exceptions import ResourceNotFoundError
        from azure.identity.aio import DefaultAzureCredential

        async with DefaultAzureCredential() as credential, self._client(credential) as blob:
            try:
                download = await blob.download_blob()
            except ResourceNotFoundError:
                return None
            data: dict[str, Any] = json.loads(await download.readall())
            return data

    async def save(self, state: dict[str, Any]) -> None:
        from azure.identity.aio import DefaultAzureCredential

        async with DefaultAzureCredential() as credential, self._client(credential) as blob:
            await blob.upload_blob(json.dumps(state), overwrite=True)
