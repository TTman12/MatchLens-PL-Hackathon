"""The Verifier: no number reaches the screen unless the evidence backs it.

For each box a lens agent drafted, the Verifier runs deterministic checks:

1. every cited evidence id exists on the moment;
2. every number in the headline and body (digits, percentages, scores, ordinals,
   number words) matches a value in the cited evidence;
3. every player named is part of the moment or its evidence;
4. headline and body fit the fact-box limits;
5. Club-lens text passes the tone check (Azure AI Content Safety when configured,
   a local word list otherwise).

Then it rules:

- **approved**: no issues;
- **repaired**: the only problem was a number backed by evidence the draft forgot to
  cite (the citation is added), or a repair agent rewrote the box and it now passes;
- **fallback**: the draft could not be repaired, or its agent failed, so the box is
  rebuilt from the template, which uses evidence values only;
- **rejected**: not even the template passes, so nothing is shown.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from matchlens.contracts import Draft, EvidenceItem, Lens, Verdict

from . import templates
from .lenses import AgentCaller, parse_json, prompt
from .numbers import backing, unsupported
from .providers import AgentTask, ProviderError
from .state import DraftResult, MomentContext, TemplateRef
from .trace import AgentTrace

HEADLINE_MAX = 80
BODY_MAX = 280


class ToneChecker(Protocol):
    name: str

    async def check(self, text: str) -> list[str]:
        """Problems with the tone of ``text``; empty if it is fine to air."""
        ...


class LocalToneChecker:
    """A small word list for offline runs. Production uses Azure AI Content Safety."""

    name = "local"
    BLOCKED = frozenset(
        {
            "idiot",
            "idiots",
            "moron",
            "morons",
            "scum",
            "pathetic",
            "disgrace",
            "trash",
            "rubbish",
            "useless",
            "hate",
            "kill",
            "die",
            "clown",
            "clowns",
            "loser",
            "losers",
        }
    )

    async def check(self, text: str) -> list[str]:
        words = set(re.findall(r"[a-záéíóúñ']+", text.lower()))
        hits = sorted(words & self.BLOCKED)
        return [f"tone: '{w}' is not playful" for w in hits]


class ContentSafetyToneChecker:
    """Azure AI Content Safety text analysis. Rejects anything at severity 2 or above."""

    name = "azure-content-safety"

    def __init__(self, endpoint: str, credential: Any | None = None, threshold: int = 2) -> None:
        from azure.ai.contentsafety.aio import ContentSafetyClient
        from azure.identity.aio import DefaultAzureCredential

        self._client = ContentSafetyClient(endpoint, credential or DefaultAzureCredential())
        self.threshold = threshold

    async def check(self, text: str) -> list[str]:
        from azure.ai.contentsafety.models import AnalyzeTextOptions

        try:
            result = await self._client.analyze_text(AnalyzeTextOptions(text=text))
        except Exception as exc:  # fail closed: if the check cannot run, do not air
            return [f"tone: content safety unavailable ({type(exc).__name__})"]
        return [
            f"tone: {c.category} severity {c.severity}"
            for c in result.categories_analysis
            if (c.severity or 0) >= self.threshold
        ]


def tone_checker_from_env(env: Mapping[str, str]) -> ToneChecker:
    endpoint = env.get("AZURE_CONTENT_SAFETY_ENDPOINT", "").strip()
    if endpoint:
        try:
            return ContentSafetyToneChecker(endpoint)
        except ImportError:
            pass
    return LocalToneChecker()


@dataclass
class Check:
    issues: list[str]
    missing_citations: list[str]
    """Evidence ids that back an uncited number; adding them fixes those issues."""
    fixable: bool


class Verifier:
    def __init__(
        self,
        caller: AgentCaller,
        trace: AgentTrace,
        tone: ToneChecker | None = None,
        player_names: Mapping[str, str] | None = None,
    ) -> None:
        self.caller = caller
        self.trace = trace
        self.tone = tone or LocalToneChecker()
        self.player_names = dict(player_names or {})

    async def check(self, ctx: MomentContext, draft: Draft) -> Check:
        issues: list[str] = []
        known = {i.id: i for i in ctx.ledger.items}
        unknown = [e for e in draft.evidence_ids if e not in known]
        if unknown:
            issues.append(f"cites evidence the moment does not have: {', '.join(unknown)}")
        cited = [known[e] for e in draft.evidence_ids if e in known]
        missing: list[str] = []
        only_citations = True
        for part, text in (("headline", draft.headline), ("body", draft.body)):
            for claim in unsupported(text, cited):
                found = backing(claim, ctx.ledger.items)
                if found:
                    missing.append(found[0])
                    issues.append(f"{part} '{claim.text}' is backed by {found[0]}, not cited")
                else:
                    only_citations = False
                    issues.append(f"{part} states '{claim.text}', which no evidence backs")
        for name in self._stray_names(ctx, draft, cited):
            only_citations = False
            issues.append(f"names {name}, who is not part of this moment")
        if len(draft.headline) > HEADLINE_MAX:
            only_citations = False
            issues.append(f"headline is {len(draft.headline)} characters, limit {HEADLINE_MAX}")
        if len(draft.body) > BODY_MAX:
            only_citations = False
            issues.append(f"body is {len(draft.body)} characters, limit {BODY_MAX}")
        if draft.lens is Lens.CLUB:
            tone = await self.tone.check(f"{draft.headline}. {draft.body}")
            if tone:
                only_citations = False
                issues.extend(tone)
        if unknown:
            only_citations = False
        return Check(issues, list(dict.fromkeys(missing)), bool(issues) and only_citations)

    def _stray_names(
        self, ctx: MomentContext, draft: Draft, cited: list[EvidenceItem]
    ) -> list[str]:
        allowed = {ctx.names.get(c.player_id, "") for c in ctx.contributors}
        allowed |= {
            n
            for n in (ctx.names.get(str(v)) for v in ctx.facts.values() if isinstance(v, str))
            if n
        }
        evidence_text = " ".join(i.value for i in ctx.ledger.items)
        text = f"{draft.headline} {draft.body}"
        stray = []
        for name in sorted(set(self.player_names.values())):
            if (
                name
                and re.search(rf"\b{re.escape(name)}\b", text)
                and name not in allowed
                and name not in evidence_text
            ):
                stray.append(name)
        return stray

    async def verify(
        self, ctx: MomentContext, results: list[DraftResult]
    ) -> dict[str, DraftResult]:
        """Rule on every box draft. Returns the drafts that may be shown, by key."""
        approved: dict[str, DraftResult] = {}
        for result in results:
            key = result.key
            original = self._sanitised(ctx, result.draft)
            self._store_draft(ctx, key, original)
            if result.draft.kind == "no_box":
                continue
            final, verdict = await self._rule(ctx, result)
            ctx.moment.verdicts[key] = verdict
            if final is not None:
                approved[key] = final
        ctx.sync()
        return approved

    async def _rule(
        self, ctx: MomentContext, result: DraftResult
    ) -> tuple[DraftResult | None, Verdict]:
        key, draft = result.key, result.draft
        instance = f"verifier:{key}"
        started = time.perf_counter()
        if draft.author == "template" and result.status in ("timeout", "error", "capped"):
            check = await self.check(ctx, draft)
            if not check.issues:
                reason = {
                    "timeout": "agent timed out",
                    "error": "agent failed",
                    "capped": "below the top 5 contributors",
                }[result.status]
                self.trace.add(
                    ctx.moment_id,
                    "verifier",
                    instance,
                    "verify",
                    "fallback",
                    f"{reason}; template box checked",
                    started,
                )
                issue = [f"{reason}; template box used"]
                return result, Verdict(status="fallback", issues=issue, final=draft)

        check = await self.check(ctx, draft)
        if not check.issues:
            self.trace.add(ctx.moment_id, "verifier", instance, "verify", "ok", "approved", started)
            return result, Verdict(status="approved")

        if check.fixable:
            fixed = draft.model_copy(
                update={
                    "evidence_ids": list(
                        dict.fromkeys(draft.evidence_ids + check.missing_citations)
                    )
                }
            )
            if not (await self.check(ctx, fixed)).issues:
                self.trace.add(
                    ctx.moment_id,
                    "verifier",
                    instance,
                    "verify",
                    "repaired",
                    "; ".join(check.issues),
                    started,
                )
                return (
                    DraftResult(key, fixed, result.template, result.status),
                    Verdict(status="repaired", issues=check.issues, final=fixed),
                )

        self.trace.add(
            ctx.moment_id,
            "verifier",
            instance,
            "verify",
            "rejected",
            "; ".join(check.issues),
            started,
        )
        repaired = await self._repair(ctx, result, check.issues)
        if repaired is not None:
            recheck = await self.check(ctx, repaired)
            if draft.body and not repaired.body:
                recheck.issues.append("repair removed the whole body")
            if not recheck.issues:
                self.trace.add(
                    ctx.moment_id, "verifier", instance, "repair", "repaired", repaired.headline
                )
                # A repair that lands on the template's exact text keeps the template, so
                # the Translator can still render it in every language.
                ref = self._template_for(ctx, result)
                same = ref is not None and templates.render(ref, "en") == (
                    repaired.headline,
                    repaired.body,
                )
                return (
                    DraftResult(key, repaired, ref if same else None, result.status),
                    Verdict(status="repaired", issues=check.issues, final=repaired),
                )
            self.trace.add(
                ctx.moment_id, "verifier", instance, "repair", "rejected", "; ".join(recheck.issues)
            )

        fallback_ref = result.template if draft.author == "template" else None
        fallback_ref = fallback_ref or self._template_for(ctx, result)
        if fallback_ref is not None:
            fb = templates.to_draft(fallback_ref, draft.lens, draft.subject_id)
            if not (await self.check(ctx, fb)).issues:
                self.trace.add(
                    ctx.moment_id, "verifier", instance, "fallback", "fallback", fb.headline
                )
                return (
                    DraftResult(key, fb, fallback_ref, result.status),
                    Verdict(status="fallback", issues=check.issues, final=fb),
                )
        self.trace.add(
            ctx.moment_id,
            "verifier",
            instance,
            "fallback",
            "rejected",
            "template did not pass either; nothing shown",
        )
        return None, Verdict(status="rejected", issues=check.issues)

    def _template_for(self, ctx: MomentContext, result: DraftResult) -> TemplateRef | None:
        draft = result.draft
        if draft.lens is Lens.PLAYER and draft.subject_id:
            return templates.player_template(ctx, draft.subject_id)
        home, away = ctx.facts.get("home_id"), ctx.facts.get("away_id")
        if not isinstance(home, str) or not isinstance(away, str):
            return None
        if draft.lens is Lens.CLUB and draft.subject_id:
            return templates.club_template(ctx, draft.subject_id, home, away)
        if draft.lens is Lens.PUNDIT:
            return templates.pundit_template(ctx, home, away)
        return None

    async def _repair(
        self, ctx: MomentContext, result: DraftResult, issues: list[str]
    ) -> Draft | None:
        draft = result.draft
        task = AgentTask(
            agent="verifier",
            instance=f"verifier:{result.key}",
            instructions=prompt("verifier"),
            prompt=json.dumps(
                {
                    "draft": {
                        "headline": draft.headline,
                        "body": draft.body,
                        "evidence_ids": draft.evidence_ids,
                    },
                    "issues": issues,
                    "evidence": [
                        {"id": i.id, "fact": i.value, "numbers": i.numbers}
                        for i in ctx.ledger.items
                    ],
                }
            ),
            payload={
                "ctx": ctx,
                "draft": draft,
                "issues": issues,
                "template": self._template_for(ctx, result),
            },
        )
        try:
            data = parse_json(await self.caller.provider.complete(task))
        except (ProviderError, TimeoutError) as exc:
            self.trace.add(ctx.moment_id, "verifier", task.instance, "repair", "error", str(exc))
            return None
        try:
            return Draft(
                lens=draft.lens,
                subject_id=draft.subject_id,
                kind="box",
                headline=str(data.get("headline", "")),
                body=str(data.get("body", "")),
                evidence_ids=[str(i) for i in data.get("evidence_ids", [])],
                author="agent",
                agent=f"{draft.agent or draft.lens}+verifier",
            )
        except ValueError:
            return None

    @staticmethod
    def _sanitised(ctx: MomentContext, draft: Draft) -> Draft:
        """The draft as stored on the moment: unknown evidence ids are dropped, since the
        contract rejects them (the verdict records the problem)."""
        known = {i.id for i in ctx.ledger.items}
        return draft.model_copy(
            update={"evidence_ids": [e for e in draft.evidence_ids if e in known]}
        )

    @staticmethod
    def _store_draft(ctx: MomentContext, key: str, draft: Draft) -> None:
        kind, _, subject = key.partition(":")
        if kind == "player":
            ctx.moment.drafts.player[subject] = draft
        elif kind == "club":
            ctx.moment.drafts.club[subject] = draft
        else:
            ctx.moment.drafts.pundit = draft
