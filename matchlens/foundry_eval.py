"""Foundry Evaluations on the lines that go on screen.

The Verifier already proves every number on a card against the tables. That leaves the words: the
Interpreter's one-line read of each card and the Analyst's "what next" line, for the neutral viewer
and for each club's fans. This scores them with the Azure AI Evaluation SDK, as a Foundry
evaluation run you can open in the portal:

- **groundedness**: does the line say only what the card's facts support? (AI-judged, 1 to 5)
- **relevance**: does it answer the card's question for that viewer? (AI-judged, 1 to 5)
- **coherence**: does it read as one clear thought? (AI-judged, 1 to 5)
- **numbers_on_card**: is every number in the line on the card? (code, 0 or 1)

The judge is the project's own model deployment, signed in with Microsoft Entra ID. The results go
to the Foundry project's Evaluations page and to a Markdown report, worst lines included, so the
weak spots are on the record rather than hidden.

    matchlens-foundry-eval web/data --out out/foundry-eval        # judge on Foundry
    matchlens-foundry-eval web/data --out out/eval --offline      # the code check only, no Azure
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from statistics import mean
from typing import Any

from .agents.safety import endpoint_from_project

JUDGED = ("groundedness", "relevance", "coherence")
PASS = 3  # the SDK's default threshold for the 1-5 judges
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?%?")


def _stat(s: dict[str, Any], teams: dict[str, str]) -> str:
    who = s.get("player") or teams.get(s["team"], s["team"])
    window = f" {s['window']}" if s.get("window") else ""
    unit = f" {s['unit']}" if s.get("unit") else ""
    return f"- {who}: {s['label']}, {s['usual']} {s.get('usual_label') or 'before'} -> {s['value']}{unit}{window}"


def card_context(b: dict[str, Any], c: dict[str, Any]) -> str:
    """What the card shows and knows, in words: the evidence a line may use."""
    teams = {t["team_id"]: t["name"] for t in b["teams"]}
    home, away = (t["team_id"] for t in b["teams"])
    score = b["score"][min(c["at"], len(b["score"]) - 1)]
    mo = c.get("momentum") or {}
    gainer = teams.get(mo.get("gainer") or "", "neither team")
    lines = [
        f"{teams[home]} (home) v {teams[away]} (away), {c['clock']}, score {score[0]}-{score[1]}.",
        f"Card: {c.get('tag', '')}. {c.get('anchor', '')}.",
        f"Momentum ({teams[home]}'s share of final-third play): {mo.get('before', 0):.0f}% before, "
        f"{mo.get('now', 0):.0f}% now. Gained by {gainer}.",
        f"Cause the agents settled on: {str(c.get('cause', '')).replace('_', ' ')}"
        + (f" ({str(c['story']).replace('_', ' ')})" if c.get("story") else "")
        + ".",
        "Stats on the card:",
        *(_stat(s, teams) for s in c["stats"]),
    ]
    return "\n".join(lines)


def rows(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per line on screen: each card's read and each analysis line, per viewer."""
    out: list[dict[str, Any]] = []
    for b in bundles:
        teams = {t["team_id"]: t["name"] for t in b["teams"]}

        def viewer(lens: str, teams: dict[str, str] = teams) -> str:
            return "a neutral viewer" if lens == "neutral" else f"a fan of {teams.get(lens, lens)}"

        for c in b["cards"]:
            ctx = card_context(b, c)
            for lens, text in (c.get("text") or {}).items():
                out.append(
                    {
                        "match": b["match_id"],
                        "clock": c["clock"],
                        "agent": "interpreter",
                        "lens": lens,
                        "query": f"In one line for {viewer(lens)}, explain why momentum shifted at {c['clock']}.",
                        "response": text,
                        "context": ctx,
                    }
                )
            for lens, a in (c.get("analysis") or {}).items():
                if not a or not a.get("line"):
                    continue
                team = teams.get(a["team"], a["team"])
                out.append(
                    {
                        "match": b["match_id"],
                        "clock": c["clock"],
                        "agent": "analyst",
                        "lens": lens,
                        "query": f"In one line for {viewer(lens)}, say what {team} should do next at {c['clock']}.",
                        "response": a["line"],
                        "context": ctx + "\nThe stat this line points to:\n" + _stat(a["stat"], teams),
                    }
                )
    return out


class NumbersOnCard:
    """Code evaluator: every number in the line appears in the card's facts."""

    def __call__(self, *, response: str, context: str) -> dict[str, Any]:
        on_card = {n.rstrip("%") for n in NUMBER.findall(context)}
        stray = [n for n in NUMBER.findall(response) if n.rstrip("%") not in on_card]
        return {"numbers_on_card": 0.0 if stray else 1.0, "numbers_stray": ", ".join(stray)}


class Remembered:
    """An evaluator that answers each row once, so a retry after a failed upload is free."""

    def __init__(self, inner: Callable[..., dict[str, Any]], fields: tuple[str, ...]) -> None:
        self.inner, self.fields = inner, fields
        self.seen: dict[tuple[str, ...], dict[str, Any]] = {}
        self.lock = threading.Lock()

    def __call__(self, *, query: str, response: str, context: str) -> dict[str, Any]:
        args = {"query": query, "response": response, "context": context}
        key = tuple(args[f] for f in self.fields)
        with self.lock:
            if key in self.seen:
                return self.seen[key]
        result = self.inner(**{f: args[f] for f in self.fields})
        with self.lock:
            self.seen[key] = result
        return result


def judges(endpoint: str, model: str) -> dict[str, Callable[..., dict[str, Any]]]:
    from azure.ai import evaluation
    from azure.identity import DefaultAzureCredential

    ev: Any = evaluation  # the SDK is untyped

    account = endpoint_from_project(endpoint)
    config = {"azure_endpoint": account, "azure_deployment": model, "api_version": "2024-10-21"}
    cred = DefaultAzureCredential()
    return {
        "groundedness": Remembered(ev.GroundednessEvaluator(config, credential=cred), ("query", "response", "context")),
        "relevance": Remembered(ev.RelevanceEvaluator(config, credential=cred), ("query", "response")),
        "coherence": Remembered(ev.CoherenceEvaluator(config, credential=cred), ("query", "response")),
    }


def run(data: Path, out: Path, offline: bool, limit: int | None) -> dict[str, Any]:
    bundles = [json.loads(p.read_text()) for p in sorted(data.glob("*.json")) if p.name != "index.json"]
    table = rows(bundles)[:limit] if limit else rows(bundles)
    out.mkdir(parents=True, exist_ok=True)
    src = out / "rows.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in table))
    evaluators: dict[str, Callable[..., dict[str, Any]]] = {"numbers": NumbersOnCard()}
    studio_url = None
    if offline:
        results = [r | {f"outputs.numbers.{k}": v for k, v in NumbersOnCard()(**_rc(r)).items()} for r in table]
    else:
        from azure.ai.evaluation import evaluate

        endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "").strip()
        if not endpoint:
            raise SystemExit("set AZURE_AI_PROJECT_ENDPOINT to the Foundry project endpoint")
        model = os.environ.get("AZURE_AI_MODEL", "").strip() or "gpt-4.1-mini"
        evaluators |= judges(endpoint, model)
        kw: dict[str, Any] = {"data": str(src), "evaluators": evaluators, "evaluation_name": f"matchlens-lines-{len(table)}"}
        try:
            res = evaluate(**kw, azure_ai_project=endpoint, tags={"app": "matchlens", "data": data.name})
        except Exception as exc:  # scoring worked but the upload didn't: keep the scores, say so
            print(f"could not log the run to the Foundry project ({type(exc).__name__}: {exc}); scoring locally")
            res = evaluate(**kw)
        studio_url = res.get("studio_url")
        outputs = [{k: v for k, v in row.items() if k.startswith("outputs.")} for row in res["rows"]]
        results = [r | o for r, o in zip(table, outputs, strict=True)]
    (out / "results.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in results))
    summary = summarise(results, studio_url)
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    (out / "report.md").write_text(report(summary, results))
    return summary


def _rc(r: dict[str, Any]) -> dict[str, str]:
    return {"response": r["response"], "context": r["context"]}


def _score(r: dict[str, Any], metric: str) -> float | None:
    v = r.get("outputs.numbers.numbers_on_card" if metric == "numbers" else f"outputs.{metric}.{metric}")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def summarise(results: list[dict[str, Any]], studio_url: str | None) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        groups["all"].append(r)
        groups[r["agent"]].append(r)
        groups[f"{r['agent']} / {'neutral' if r['lens'] == 'neutral' else 'club'}"].append(r)
    table: dict[str, dict[str, Any]] = {}
    for name, rs in groups.items():
        row: dict[str, Any] = {"lines": len(rs)}
        nums = [x for r in rs if (x := _score(r, "numbers")) is not None]
        row["numbers_on_card"] = round(mean(nums), 3) if nums else None
        for m in JUDGED:
            xs = [x for r in rs if (x := _score(r, m)) is not None]
            if xs:
                row[m] = round(mean(xs), 2)
                row[f"{m}_pass"] = round(sum(x >= PASS for x in xs) / len(xs), 3)
        table[name] = row
    return {"studio_url": studio_url, "groups": table}


def report(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    judged = any(m in summary["groups"].get("all", {}) for m in JUDGED)
    head = ["Lines", "Numbers on card", *([f"{m.title()} (mean, pass)" for m in JUDGED] if judged else [])]
    lines = [
        "# Foundry evaluation of the on-screen lines",
        "",
        "Generated by `matchlens-foundry-eval`. Judges: Azure AI Evaluation SDK on the project's model; "
        "a line passes a judge at 3 or more out of 5.",
        "",
    ]
    if summary.get("studio_url"):
        lines += [f"Foundry run: {summary['studio_url']}", ""]
    lines += ["| Group | " + " | ".join(head) + " |", "|" + "---|" * (len(head) + 1)]
    for name, row in summary["groups"].items():
        cells = [str(row["lines"]), f"{row['numbers_on_card']:.0%}" if row["numbers_on_card"] is not None else "-"]
        if judged:
            cells += [f"{row[m]:.2f}, {row[f'{m}_pass']:.0%}" if m in row else "-" for m in JUDGED]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    worst = sorted(
        (r for r in results if _score(r, "groundedness") is not None or _score(r, "numbers") == 0),
        key=lambda r: (_score(r, "groundedness") or 0, _score(r, "numbers") or 0),
    )[:8]
    if worst:
        lines += ["", "## The weakest lines", ""]
        for r in worst:
            g = _score(r, "groundedness")
            why = r.get("outputs.groundedness.groundedness_reason") or r.get("outputs.numbers.numbers_stray") or ""
            score = f"groundedness {g:.0f}" if g is not None else "stray numbers"
            lines.append(f"- **{r['match']} {r['clock']} {r['agent']} ({r['lens']})**, {score}: “{r['response']}”")
            if why:
                lines.append(f"  - {str(why)[:300]}")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path, nargs="?", default=Path("web/data"), help="folder of match bundles")
    ap.add_argument("--out", type=Path, default=Path("out/foundry-eval"))
    ap.add_argument("--offline", action="store_true", help="run the code check only, with no Azure calls")
    ap.add_argument("--limit", type=int, help="score only the first N lines")
    args = ap.parse_args()
    summary = run(args.data, args.out, args.offline, args.limit)
    print((args.out / "report.md").read_text())
    if summary.get("studio_url"):
        print(f"Foundry run: {summary['studio_url']}")


if __name__ == "__main__":
    main()
