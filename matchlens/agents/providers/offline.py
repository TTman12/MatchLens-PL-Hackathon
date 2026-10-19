"""Deterministic provider: answers every agent task without a model.

Lens tasks are written from the templates, repair tasks drop the sentences that broke
a rule, and translation tasks re-render the template in the target language. Output
has the same JSON shape a model is asked for, so the rest of the pipeline cannot tell
the difference.
"""

from __future__ import annotations

import json
import re
from typing import Any

from matchlens.agents import templates
from matchlens.agents.numbers import unsupported
from matchlens.agents.state import MomentContext, TemplateRef

from .base import AgentTask, ProviderError


def _ref_json(ref: TemplateRef, lang: str = "en") -> str:
    headline, body = templates.render(ref, lang)
    return json.dumps(
        {
            "kind": "box",
            "headline": headline,
            "body": body,
            "evidence_ids": ref.evidence_ids,
            "template": {"key": ref.key, "params": ref.params, "parts": ref.parts},
        }
    )


class OfflineProvider:
    name = "offline"

    async def complete(self, task: AgentTask) -> str:
        p = task.payload
        if task.agent in ("player", "club", "pundit"):
            ref = p.get("template")
            if not isinstance(ref, TemplateRef):
                raise ProviderError(f"{task.instance}: offline lens task needs a template")
            return _ref_json(ref)
        if task.agent == "verifier":
            return self._repair(p)
        if task.agent == "translator":
            ref = p.get("template")
            if not isinstance(ref, TemplateRef):
                raise ProviderError("offline translation needs a template-written draft")
            headline, body = templates.render(ref, str(p["lang"]))
            return json.dumps({"headline": headline, "body": body})
        raise ProviderError(f"offline provider has no answer for agent {task.agent!r}")

    def _repair(self, p: dict[str, Any]) -> str:
        """Keep only the sentences whose numbers the cited evidence backs."""
        ctx: MomentContext = p["ctx"]
        draft = p["draft"]
        cited = [i for i in ctx.ledger.items if i.id in draft.evidence_ids]
        sentences = re.split(r"(?<=[.!?])\s+", draft.body.strip()) if draft.body else []
        kept = [s for s in sentences if s and not unsupported(s, cited)]
        headline = draft.headline
        if unsupported(headline, cited):
            fallback: TemplateRef | None = p.get("template")
            if fallback is None:
                raise ProviderError("headline cannot be repaired without a template")
            headline, _ = templates.render(fallback, "en")
            cited_ids = list(dict.fromkeys(draft.evidence_ids + fallback.evidence_ids))
        else:
            cited_ids = list(draft.evidence_ids)
        return json.dumps(
            {"kind": "box", "headline": headline, "body": " ".join(kept), "evidence_ids": cited_ids}
        )
