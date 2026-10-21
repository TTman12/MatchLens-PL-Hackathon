"""Azure AI Content Safety on every line the agents write for the screen.

The Interpreter and the Analyst write free text that goes on air. Before a draft is accepted, each
line is sent to Content Safety's text analysis (hate, sexual, violence, self-harm). A line at or
above ``SEVERITY`` in any category counts as a problem, like a wrong number: the draft goes back
once with the problem listed, then falls back to the rule-written lines.

Content Safety runs on the same Foundry (AI Services) account as the models, signed in with
Microsoft Entra ID, so there is no key. The endpoint is ``AZURE_CONTENT_SAFETY_ENDPOINT``, or the
account behind ``AZURE_AI_PROJECT_ENDPOINT``. If the service can't be reached the lines go out
unscreened and the count says so; the run never stops for it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)

ENDPOINT_VAR = "AZURE_CONTENT_SAFETY_ENDPOINT"
SEVERITY = 2  # 0 safe, 2 low, 4 medium, 6 high: football banter should score 0


def endpoint_from_project(project_endpoint: str) -> str:
    """https://<account>.services.ai.azure.com/api/projects/<p> -> https://<account>.cognitiveservices.azure.com/"""
    host = urlparse(project_endpoint).hostname or ""
    account = host.split(".")[0]
    return f"https://{account}.cognitiveservices.azure.com/" if account else ""


@dataclass
class SafetyCount:
    screened: int = 0
    flagged: int = 0
    unscreened: int = 0
    categories: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"screened": self.screened, "flagged": self.flagged, "unscreened": self.unscreened, "categories": self.categories}


class ContentSafety:
    def __init__(self, credential: Any, endpoint: str | None = None) -> None:
        self.endpoint = (endpoint or os.environ.get(ENDPOINT_VAR, "")).strip() or endpoint_from_project(
            os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
        )
        self.count = SafetyCount()
        self._client: Any = None
        self._broken = not self.endpoint
        if not self._broken:
            try:
                from azure.ai.contentsafety.aio import ContentSafetyClient
            except ImportError:
                log.warning("Content Safety needs the 'foundry' extra; lines go out unscreened")
                self._broken = True
            else:
                self._client = ContentSafetyClient(self.endpoint, credential)

    async def problems(self, lines: dict[str, str]) -> list[str]:
        """One problem per line Content Safety flags; none if the lines are clean or unscreened."""
        out: list[str] = []
        for key, text in lines.items():
            if self._broken:
                self.count.unscreened += 1
                continue
            try:
                result = await self._client.analyze_text({"text": text[:1000]})
            except Exception as exc:  # no right to call it, region, network: never stop the match
                log.warning("Content Safety unavailable (%s); lines go out unscreened", exc)
                self._broken = True
                self.count.unscreened += 1
                continue
            self.count.screened += 1
            hits = [f"{c.category} {c.severity}" for c in result.categories_analysis if (c.severity or 0) >= SEVERITY]
            if hits:
                self.count.flagged += 1
                for c in result.categories_analysis:
                    if (c.severity or 0) >= SEVERITY:
                        self.count.categories[str(c.category)] = self.count.categories.get(str(c.category), 0) + 1
                out.append(f"Content Safety flagged the {key} line ({', '.join(hits)}). Rewrite it plainly.")
        return out

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()


async def screen(runner: Any, lines: dict[str, str]) -> list[str]:
    """Content Safety's problems with these lines, on a runner that has it (the Foundry runner)."""
    safety: ContentSafety | None = getattr(runner, "safety", None)
    return await safety.problems(lines) if safety is not None else []
