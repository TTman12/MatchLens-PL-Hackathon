"""MatchLens evals: no unverified number may reach a cue.

    python evals/run_evals.py                  # offline: verifier cases + chaos audits
    python evals/run_evals.py --foundry        # also Foundry groundedness evaluators

Three suites:

1. **Verifier cases** (``groundedness_cases.jsonl``). Hand-written drafts against the
   sample match's goal and card moments, some right and some wrong (a speed off by
   1.8 km/h, a 2-0 that was 1-0, "three lines" with no evidence for three, an invented
   player, an abusive Club line). Each must get the expected ruling.
2. **Chaos audits.** The full pipeline runs with every lens agent misquoting a number
   (``misquote:*``), and again with agents killed. The independent audit
   (``matchlens.agents.audit``) must then find every on-screen number backed by
   evidence, and every evidence number recomputed from the match data.
3. **Foundry groundedness** (``--foundry``, needs Azure). Player-lens agents run on
   Microsoft Foundry and their boxes are scored by Foundry's built-in groundedness and
   relevance evaluators, with the moment's evidence as context.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matchlens.agents.audit import AuditReport  # noqa: E402
from matchlens.agents.detector import detect_moments  # noqa: E402
from matchlens.agents.lenses import AgentCaller  # noqa: E402
from matchlens.agents.pipeline import run_match  # noqa: E402
from matchlens.agents.providers import ChaosProvider, OfflineProvider  # noqa: E402
from matchlens.agents.trace import AgentTrace  # noqa: E402
from matchlens.agents.verifier import Verifier  # noqa: E402
from matchlens.contracts import Draft, Lens  # noqa: E402
from matchlens.stats import StatsEngine, load_match  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
CASES = Path(__file__).with_name("groundedness_cases.jsonl")


@dataclass
class CaseResult:
    case_id: str
    expected: str
    got: str
    issues: list[str]

    @property
    def passed(self) -> bool:
        return self.expected == self.got


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def run_cases(
    match_dir: Path = SAMPLE, cases: list[dict[str, Any]] | None = None
) -> list[CaseResult]:
    stats = StatsEngine(load_match(match_dir))
    contexts = {str(c.moment.type): c for c in detect_moments(stats)}
    names = {pid: p.short_name for pid, p in stats.match.players.items()}
    trace = AgentTrace()
    verifier = Verifier(AgentCaller(OfflineProvider(), trace), trace, player_names=names)
    results = []
    for case in cases or load_cases():
        ctx = contexts[case["moment"]]
        ids = [ctx.ledger.refs.get(ref, ref) for ref in case["cite"]]
        draft = Draft.model_construct(
            lens=Lens(case["lens"]),
            subject_id=case["subject"],
            kind="box",
            headline=case["headline"],
            body=case["body"],
            evidence_ids=ids,
            author="agent",
            agent="eval",
        )
        check = await verifier.check(ctx, draft)
        got = "approved" if not check.issues else "repaired" if check.fixable else "rejected"
        results.append(CaseResult(case["id"], case["expect"], got, check.issues))
    return results


async def run_chaos_audits(match_dir: Path = SAMPLE) -> dict[str, AuditReport]:
    """The full pipeline under each chaos setting, audited independently."""
    settings = {
        "clean": [],
        "every-lens-misquotes": ["misquote:player", "misquote:club", "misquote:pundit"],
        "pundit-killed": ["kill:pundit"],
        "all-lens-agents-killed": ["kill:player", "kill:club", "kill:pundit"],
        "translator-killed": ["kill:translator"],
    }
    reports = {}
    for name, rules in settings.items():
        provider = (
            ChaosProvider.from_rules(OfflineProvider(), rules) if rules else OfflineProvider()
        )
        result = await run_match(match_dir, provider, languages=["en", "es"])
        with TemporaryDirectory() as tmp:
            result.write(tmp)  # audit what is written, as the player would read it
            from matchlens.agents.audit import audit_dir

            reports[name] = audit_dir(match_dir, tmp)
        # A misquoted draft must never be approved as written.
        corrupted = set(provider.corrupted) if isinstance(provider, ChaosProvider) else set()
        for m in result.moments:
            for key, verdict in m.verdicts.items():
                draft_agent = _agent_for(m, key)
                if draft_agent in corrupted and verdict.status == "approved":
                    reports[name].problems.append(f"{m.moment_id} {key} approved a misquote")
        if rules and "misquote" in rules[0] and not corrupted:
            reports[name].problems.append("chaos misquoted nothing: the eval proved nothing")
    return reports


def _agent_for(moment: Any, key: str) -> str | None:
    kind, _, subject = key.partition(":")
    drafts = moment.drafts
    draft = (
        drafts.player.get(subject)
        if kind == "player"
        else drafts.club.get(subject)
        if kind == "club"
        else drafts.pundit
    )
    return draft.agent if draft is not None else None


async def run_foundry(match_dir: Path = SAMPLE) -> list[Any]:  # pragma: no cover - needs Azure
    """Score Player-lens boxes with Foundry's groundedness and relevance evaluators."""
    from agent_framework import Agent, evaluate_agent
    from agent_framework_foundry import FoundryChatClient, FoundryEvals
    from azure.identity.aio import DefaultAzureCredential

    from matchlens.agents.lenses import moment_brief, prompt
    from matchlens.agents.providers import FoundrySettings
    from matchlens.mcp_server.tools import MatchStateStore

    settings = FoundrySettings.from_env()
    client = FoundryChatClient(
        project_endpoint=settings.endpoint,
        model=settings.fast_model,
        credential=DefaultAzureCredential(),
    )
    stats = StatsEngine(load_match(match_dir))
    store = MatchStateStore(stats)
    evals = FoundryEvals(
        client=client, evaluators=[FoundryEvals.GROUNDEDNESS, FoundryEvals.RELEVANCE]
    )
    agent = Agent(client=client, instructions=prompt("player"), name="player-agent")
    results = []
    for ctx in detect_moments(stats):
        for c in ctx.contributors[:5]:
            brief = moment_brief(ctx, store) | {
                "lens": "player",
                "player": {
                    "player_id": c.player_id,
                    "name": ctx.names.get(c.player_id),
                    "role": c.role,
                },
            }
            context = "\n".join(f"{i.id}: {i.value} {i.numbers}" for i in ctx.ledger.items)
            results += await evaluate_agent(
                agent=agent,
                queries=[json.dumps(brief)],
                evaluators=evals,
                context=context,
                eval_name=f"matchlens-{ctx.moment_id}-{c.player_id}",
            )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--foundry", action="store_true", help="Also run Foundry evaluators")
    args = parser.parse_args(argv)
    failed = 0

    cases = asyncio.run(run_cases())
    passed = sum(r.passed for r in cases)
    print(f"Verifier cases: {passed}/{len(cases)} as expected")
    for r in cases:
        if not r.passed:
            failed += 1
            print(f"  - {r.case_id}: expected {r.expected}, got {r.got} {r.issues}")

    for name, report in asyncio.run(run_chaos_audits()).items():
        print(f"Chaos audit [{name}]: {report.summary()}")
        for p in report.problems:
            failed += 1
            print("  -", p)

    if args.foundry:
        for result in asyncio.run(run_foundry()):
            print("Foundry:", result)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
