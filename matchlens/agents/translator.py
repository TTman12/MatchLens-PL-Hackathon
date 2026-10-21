"""The Translator: the screen's lines in Spanish, with a check that nothing changed on the way.

The English lines on a bundle (each card's line and analysis lines, the recap headlines) go to a
translation backend in one batch per match:

- ``azure``: Azure AI Translator (Text Translation v3). Names are wrapped so the service leaves them
  alone. Needs ``AZURE_TRANSLATOR_KEY`` and ``AZURE_TRANSLATOR_REGION`` (and optionally
  ``AZURE_TRANSLATOR_ENDPOINT``); the free F0 tier covers a season of demo matches.
- ``agent``: the Translator agent (``matchlens-translator``) on the runner: Foundry, or offline.
- ``offline``: no translation; the rules' Spanish twin of each line (matchlens/explain/spanish.py).

Whatever the backend, a check in code compares each translation with its English line: the same
numbers, every club and player name kept exactly and no new ones, a sensible length, and no English
left in it. A failed line goes back once to the agent with its problems; after that, or with the
Azure backend, it falls back to the rules' Spanish line, or stays in English when there is none.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from .crew import parse
from .roles import TRANSLATOR
from .runners import Runner, RunnerError

KEY_VAR, REGION_VAR, ENDPOINT_VAR = "AZURE_TRANSLATOR_KEY", "AZURE_TRANSLATOR_REGION", "AZURE_TRANSLATOR_ENDPOINT"
DEFAULT_ENDPOINT = "https://api.cognitive.microsofttranslator.com"
ENGLISH = re.compile(r"\b(the|and|are|is|have|has|their|they|with|from|keep|getting|can't|isn't)\b", re.I)
SPANISH = re.compile(r"\b(el|la|los|las|de|del|que|y|en|a|con|por|para|se|su|no|le|al)\b|[áéíóúñ¿¡]", re.I)


@dataclass
class TranslateJob:
    """One match's lines. Each item: {"id", "en", "fallback" (the rules' Spanish, or None)}."""

    items: list[dict[str, Any]]
    names: list[str]  # every club and player name in the match
    trace: list[dict[str, Any]] = field(default_factory=list)


def _has(name: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def check_translation(en: str, es: str, names: list[str]) -> list[str]:
    """What is wrong with a Spanish line against its English one, if anything."""
    es = es.strip()
    if not es:
        return ["empty"]
    problems = []
    if sorted(re.findall(r"\d+(?:[.,]\d+)?", en)) != sorted(re.findall(r"\d+(?:[.,]\d+)?", es)):
        problems.append("the numbers differ from the English")
    # longest first, so "Ben D." is not also counted as "Ben"
    for n in sorted(names, key=len, reverse=True):
        if _has(n, en) and not _has(n, es):
            problems.append(f"'{n}' is missing or changed")
        elif _has(n, es) and not _has(n, en) and not any(_has(m, en) and n in m for m in names):
            problems.append(f"'{n}' is not in the English")
    a, b = len(en.split()), len(es.split())
    if b < 0.6 * a or b > 1.9 * a + 2:
        problems.append(f"{b} words against {a} in the English")
    stripped = es
    for n in names:
        stripped = stripped.replace(n, "")
    if es == en.strip() or len(ENGLISH.findall(stripped)) >= 2 or not SPANISH.search(stripped):
        problems.append("it is not Spanish")
    return problems


class Backend(Protocol):
    @property
    def name(self) -> str: ...

    async def translate(self, job: TranslateJob, ids: list[str], problems: dict[str, list[str]] | None) -> dict[str, str]: ...


def offline_translation(job: TranslateJob) -> str:
    """The offline runner's stand-in for the agent: each line's rules twin (or nothing)."""
    return json.dumps({"lines": {i["id"]: i["fallback"] for i in job.items if i.get("fallback")}})


@dataclass
class AgentBackend:
    """The Translator agent, on whichever runner the crew uses."""

    runner: Runner

    @property
    def name(self) -> str:
        return str(self.runner.name)

    async def translate(self, job: TranslateJob, ids: list[str], problems: dict[str, list[str]] | None) -> dict[str, str]:
        en = {i["id"]: i["en"] for i in job.items if i["id"] in ids}
        parts = [f"Names in the match: {json.dumps(job.names)}", "Lines:\n" + json.dumps(en, indent=1, ensure_ascii=False)]
        if problems:
            parts.append(
                "Your last translations of these lines were rejected:\n" + json.dumps(problems, indent=1) + "\nFix them."
            )
        sub = TranslateJob([i for i in job.items if i["id"] in ids], job.names)
        out = parse(await self.runner.run(TRANSLATOR, "\n\n".join(parts), [], sub), ("lines",))["lines"]
        if not isinstance(out, dict):
            raise ValueError("lines is not an object")
        return {str(k): str(v) for k, v in out.items() if k in en}


class AzureBackend:
    """Azure AI Translator, Text Translation v3, English to Spanish."""

    name = "azure"

    def __init__(self, key: str | None = None, region: str | None = None, endpoint: str | None = None) -> None:
        self.key = key or os.environ.get(KEY_VAR, "").strip()
        self.region = region or os.environ.get(REGION_VAR, "").strip()
        self.endpoint = (endpoint or os.environ.get(ENDPOINT_VAR, "").strip() or DEFAULT_ENDPOINT).rstrip("/")
        if not self.key:
            raise RunnerError(f"set {KEY_VAR} (and {REGION_VAR}) for Azure AI Translator")

    def _protect(self, text: str, names: list[str]) -> str:
        out = html.escape(text, quote=False)
        for n in sorted(names, key=len, reverse=True):
            out = re.sub(
                rf"(?<![\w>]){re.escape(html.escape(n, quote=False))}(?![\w<])", f'<span class="notranslate">{n}</span>', out
            )
        return out

    @staticmethod
    def _unprotect(text: str) -> str:
        return html.unescape(re.sub(r'<span class="notranslate">(.*?)</span>', r"\1", text))

    def _post(self, texts: list[str]) -> list[str]:
        url = f"{self.endpoint}/translate?api-version=3.0&from=en&to=es&textType=html"
        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/json; charset=UTF-8",
            "X-ClientTraceId": str(uuid.uuid4()),
        }
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region
        req = urllib.request.Request(url, json.dumps([{"Text": t} for t in texts]).encode(), headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - fixed https endpoint
            body = json.loads(r.read())
        return [str(x["translations"][0]["text"]) for x in body]

    async def translate(self, job: TranslateJob, ids: list[str], problems: dict[str, list[str]] | None) -> dict[str, str]:
        items = [i for i in job.items if i["id"] in ids]
        out: dict[str, str] = {}
        for lo in range(0, len(items), 100):  # the service takes up to 1000 texts; keep requests small
            chunk = items[lo : lo + 100]
            try:
                done = await asyncio.to_thread(self._post, [self._protect(i["en"], job.names) for i in chunk])
            except Exception as exc:  # network, quota, auth: the lines fall back to the rules
                raise RunnerError(f"Azure AI Translator: {type(exc).__name__}: {exc}") from exc
            out.update({i["id"]: self._unprotect(t) for i, t in zip(chunk, done, strict=True)})
        return out


async def translate(backend: Backend, job: TranslateJob) -> dict[str, tuple[str, str]]:
    """id -> (Spanish line, where it came from: the backend's name, "rules" or "english")."""
    result: dict[str, tuple[str, str]] = {}
    todo = [i["id"] for i in job.items] if backend.name != "offline" else []
    problems: dict[str, list[str]] | None = None
    rounds = 1 if backend.name in ("azure", "offline") else 2
    for round_ in range(1, rounds + 1 if todo else 1):
        t0 = time.monotonic()
        try:
            got = await backend.translate(job, todo, problems)
        except (RunnerError, ValueError, TypeError, KeyError) as exc:
            job.trace.append({"round": round_, "status": "failed", "error": str(exc)[:200], "ms": _ms(t0)})
            break
        problems = {}
        en = {i["id"]: i["en"] for i in job.items}
        for i in todo:
            if i not in got:
                problems[i] = ["missing"]
                continue
            p = check_translation(en[i], got[i], job.names)
            if p:
                problems[i] = p
            else:
                result[i] = (got[i].strip(), backend.name)
        job.trace.append(
            {
                "round": round_,
                "status": "rejected" if problems else "passed",
                "lines": len(todo),
                "rejected": len(problems),
                "problems": dict(list(problems.items())[:4]),
                "ms": _ms(t0),
            }
        )
        todo = list(problems)
        if not todo:
            break
    for i in job.items:
        if i["id"] not in result:
            result[i["id"]] = (i["fallback"], "rules") if i.get("fallback") else (i["en"], "english")
    return result


def _ms(t0: float) -> int:
    return round(1000 * (time.monotonic() - t0))


def items(b: dict[str, Any]) -> list[dict[str, Any]]:
    """Every English line on a bundle, with the rules' Spanish twin where there is one."""
    out = []
    for n, c in enumerate(b["cards"]):
        es = c.get("i18n", {}).get("es", {})
        for lens, line in (c.get("text") or {}).items():
            out.append({"id": f"c{n}.text.{lens}", "en": line, "fallback": (es.get("text") or {}).get(lens)})
        for lens, a in (c.get("analysis") or {}).items():
            out.append({"id": f"c{n}.analysis.{lens}", "en": a["line"], "fallback": (es.get("analysis") or {}).get(lens)})
    r = b.get("recap")
    if r:
        for lens, line in r["text"].items():
            out.append({"id": f"recap.{lens}", "en": line, "fallback": r["i18n"]["es"]["text"].get(lens)})
    return out


async def translate_bundle(backend: Backend, b: dict[str, Any]) -> None:
    """Put a bundle's Spanish lines in place, translated and checked, and log what happened."""
    names = sorted(
        {t["short_name"] for t in b["teams"]} | {t["name"] for t in b["teams"]} | {p["name"] for p in b["stats"]["players"]}
    )
    job = TranslateJob(items(b), names)
    done = await translate(backend, job)
    sources: dict[str, int] = {}
    for key, (line, source) in done.items():
        sources[source] = sources.get(source, 0) + 1
        if key.startswith("recap."):
            b["recap"]["i18n"]["es"]["text"][key[6:]] = line
            b["recap"]["i18n"]["es"]["source"] = source
            continue
        head, part, lens = key.split(".", 2)
        if source == "english":  # the screen shows the English line itself
            continue
        es = b["cards"][int(head[1:])]["i18n"]["es"]
        es.setdefault(part, {})[lens] = line
        es.setdefault("sources", {})[f"{part}.{lens}"] = source
    b["translator"] = {"backend": backend.name, "lines": len(done), "sources": sources, "rounds": job.trace}


def make_backend(kind: str, runner: Runner | None) -> Backend:
    """azure, agent (the runner's Translator agent) or offline; "auto" is Azure when its key is set,
    else the agent on a Foundry runner, else offline."""
    if kind == "auto":
        kind = "azure" if os.environ.get(KEY_VAR) else "agent" if runner is not None and runner.name == "foundry" else "offline"
    if kind == "azure":
        return AzureBackend()
    if kind == "agent" and runner is not None:
        return AgentBackend(runner)
    from .runners import OfflineRunner

    return AgentBackend(OfflineRunner())
