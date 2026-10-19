"""The Translator: localises approved boxes, with numbers and names locked.

A translation is accepted only if it claims exactly the same numbers as the approved
English box, keeps every name, fits the box limits, and every number is still backed by
the box's evidence. A rejected attempt is retried once with the problems listed; if the
retry fails too, the box stays English-only for that language and the agent timeline
says why. The model is asked to localise, not translate word for word.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from matchlens.contracts import EvidenceItem

from .lenses import AgentCaller, parse_json, prompt
from .numbers import number_set, unsupported
from .providers import AgentTask, ProviderError
from .state import DraftResult, MomentContext
from .trace import AgentTrace
from .verifier import BODY_MAX, HEADLINE_MAX

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "pt": "Portuguese",
    "de": "German",
    "ar": "Arabic",
    "hi": "Hindi",
    "ja": "Japanese",
}
BOXED = ("fact_box", "timeline_item", "brief")


class Translator:
    def __init__(
        self, caller: AgentCaller, trace: AgentTrace, languages: list[str], names: list[str]
    ) -> None:
        self.caller = caller
        self.trace = trace
        self.languages = [lang for lang in languages if lang != "en"]
        self.names = sorted(set(names), key=len, reverse=True)
        """Every player and club name; any that the source mentions must survive."""

    async def translate(
        self,
        ctx: MomentContext | None,
        cues: list[dict[str, Any]],
        results: dict[str, DraftResult],
    ) -> list[dict[str, Any]]:
        """The cues in every target language, to add to the English ones."""
        jobs = [
            self._one(ctx, cue, results.get(cue.get("_key", "")), lang)
            for cue in cues
            if str(cue["template"]) in BOXED and cue.get("box")
            for lang in self.languages
        ]
        translated = await asyncio.gather(*jobs)
        return [c for c in translated if c is not None]

    async def _one(
        self, ctx: MomentContext | None, cue: dict[str, Any], result: DraftResult | None, lang: str
    ) -> dict[str, Any] | None:
        box = cue["box"]
        moment_id = cue.get("moment_id")
        instance = f"translator:{lang}:{cue.get('_key', 'brief')}"
        request: dict[str, Any] = {
            "target_language": LANGUAGE_NAMES.get(lang, lang),
            "headline": box["headline"],
            "body": box["body"],
        }
        problems: list[str] = []
        headline = body = ""
        for attempt in range(1 + self.caller.retries):
            if problems:
                # Show the model its rejected attempt and exactly which lock it broke.
                request |= {
                    "rejected_attempt": {"headline": headline, "body": body},
                    "problems": problems,
                }
            task = AgentTask(
                agent="translator",
                instance=instance,
                instructions=prompt("translator"),
                prompt=json.dumps(request, ensure_ascii=False),
                payload={
                    "lang": lang,
                    "template": result.template if result else cue.get("_template"),
                    "headline": box["headline"],
                    "body": box["body"],
                },
            )
            started = time.perf_counter()
            try:
                reply = await asyncio.wait_for(
                    self.caller.provider.complete(task), self.caller.timeout_s
                )
                data = parse_json(reply)
            except (ProviderError, TimeoutError) as exc:
                self.trace.add(
                    moment_id,
                    "translator",
                    instance,
                    "translate",
                    "skipped",
                    f"kept English only: {exc or 'timed out'}",
                    started,
                )
                return None
            headline, body = str(data.get("headline", "")), str(data.get("body", ""))
            problems = self._lock_problems(box, headline, body, lang)
            if not problems:
                status = "ok" if attempt == 0 else "retried"
                self.trace.add(
                    moment_id, "translator", instance, "translate", status, headline, started
                )
                return cue | {"lang": lang, "box": box | {"headline": headline, "body": body}}
            if attempt < self.caller.retries:
                self.trace.add(
                    moment_id,
                    "translator",
                    instance,
                    "translate",
                    "retry",
                    "; ".join(problems) + "; retrying with the problems listed",
                    started,
                )
        self.trace.add(
            moment_id, "translator", instance, "translate", "rejected", "; ".join(problems), started
        )
        return None

    def _lock_problems(self, box: dict[str, Any], headline: str, body: str, lang: str) -> list[str]:
        problems = []
        source = f"{box['headline']} {box['body']}"
        target = f"{headline} {body}"
        if number_set(source, "en") != number_set(target, lang):
            problems.append(
                f"numbers changed: {number_set(source, 'en')} became {number_set(target, lang)}"
            )
        evidence = [EvidenceItem.model_validate(e) for e in box.get("evidence", [])]
        bad = unsupported(target, evidence, lang)
        if bad:
            problems.append("unbacked numbers: " + ", ".join(c.text for c in bad))
        for name in self.names:
            if re.search(rf"\b{re.escape(name)}\b", source) and name not in target:
                problems.append(f"name '{name}' missing")
        if not headline or len(headline) > HEADLINE_MAX:
            problems.append(f"headline is {len(headline)} characters; the limit is {HEADLINE_MAX}")
        if len(body) > BODY_MAX:
            problems.append(f"body is {len(body)} characters; the limit is {BODY_MAX}")
        return problems
