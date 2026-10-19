"""Run the whole agent pipeline on one match and write moments, cues and the agent trace.

    matchlens-agents data/sample --out out/sample                 # offline, no credentials
    matchlens-agents data/sample --out out/sample --chaos kill:pundit
    MATCHLENS_PROVIDER=foundry matchlens-agents data/sample --out out/sample

Outputs, in the formats of ``docs/contracts.md``:

- ``moments.json``: every moment with evidence, drafts, verdicts and director decision;
- ``cues.json``: the cue track for every lens, contributor and language;
- ``agent_trace.json``: the agent timeline for the "Under the hood" drawer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from matchlens.contracts import SCHEMA_VERSION, Cue, CueTrack, EventType, Layer, Moment
from matchlens.mcp_server.tools import MatchStateStore
from matchlens.stats import MatchData, StatsEngine, load_match

from .briefs import write_brief
from .detector import detect_moments
from .director import Director, DirectorConfig
from .lenses import AgentCaller, ClubLens, PlayerLens, PunditLens
from .providers import ModelProvider, OfflineProvider, configure_tracing, provider_from_env
from .state import MomentContext, MomentJob
from .trace import AgentTrace
from .translator import Translator
from .verifier import Verifier, tone_checker_from_env
from .workflow import AgentFrameworkRunner, PlainRunner, Stages

Engine = Literal["agent-framework", "asyncio"]
LAYER_ORDER = {Layer.GLOBAL: 0, Layer.PLAYER: 1, Layer.CLUB: 2, Layer.PUNDIT: 3}


@dataclass
class PipelineResult:
    moments: list[Moment]
    cues: CueTrack
    trace: AgentTrace
    contexts: list[MomentContext] = field(default_factory=list, repr=False)

    def write(self, out_dir: Path | str) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        moments = [m.model_dump(mode="json") for m in self.moments]
        (out / "moments.json").write_text(json.dumps(moments, indent=2) + "\n", encoding="utf-8")
        (out / "cues.json").write_text(
            json.dumps(self.cues.model_dump(mode="json", exclude_none=True), indent=2) + "\n",
            encoding="utf-8",
        )
        self.trace.write(out / "agent_trace.json")


def build_stages(
    stats: StatsEngine,
    store: MatchStateStore,
    provider: ModelProvider,
    trace: AgentTrace,
    languages: list[str],
    *,
    timeout_s: float,
    director: DirectorConfig | None = None,
) -> Stages:
    caller = AgentCaller(provider, trace, timeout_s=timeout_s)
    match = stats.match
    player_names = {pid: p.short_name for pid, p in match.players.items()}
    names = list(player_names.values()) + [c.short_name for c in match.league.clubs]
    return Stages(
        player=PlayerLens(caller, store),
        club=ClubLens(caller, store),
        pundit=PunditLens(caller, store),
        verifier=Verifier(caller, trace, tone_checker_from_env(os.environ), player_names),
        director=Director(stats, trace, director),
        translator=Translator(caller, trace, languages, names),
        trace=trace,
    )


async def run_match(
    match: MatchData | Path | str,
    provider: ModelProvider | None = None,
    *,
    languages: list[str] | None = None,
    engine: Engine = "agent-framework",
    timeout_s: float | None = None,
    director: DirectorConfig | None = None,
) -> PipelineResult:
    """Detect moments, run every agent, and return moments, cues and the agent trace."""
    data = match if isinstance(match, MatchData) else load_match(match)
    provider = provider or OfflineProvider()
    languages = languages or ["en", "es"]
    if "en" not in languages:
        languages = ["en", *languages]
    timeout = timeout_s if timeout_s is not None else (5.0 if provider.name == "offline" else 20.0)

    stats = StatsEngine(data)
    store = MatchStateStore(stats)
    trace = AgentTrace(provider=provider.name)
    stages = build_stages(
        stats, store, provider, trace, languages, timeout_s=timeout, director=director
    )
    runner: AgentFrameworkRunner | PlainRunner
    try:
        runner = (
            AgentFrameworkRunner(stages) if engine == "agent-framework" else PlainRunner(stages)
        )
    except ImportError:
        trace.add(
            None,
            "pipeline",
            "pipeline",
            "start",
            "degraded",
            "agent-framework not installed: running stages with asyncio",
        )
        runner = PlainRunner(stages)

    contexts = detect_moments(stats)
    for ctx in contexts:
        store.add_moment(ctx.moment)

    cues: list[dict[str, Any]] = []
    period_ends = [e for e in data.events if e.type is EventType.PERIOD_END]
    done: list[MomentContext] = []
    for ctx in contexts:
        for end in [e for e in period_ends if e.t < ctx.moment.t_peak]:
            cues += await _brief(stages, end, done, data, stats)
            period_ends.remove(end)
        outcome = await runner.run(MomentJob(ctx))
        cues += outcome.cues
        done.append(ctx)
    for end in period_ends:
        cues += await _brief(stages, end, done, data, stats)

    track = _cue_track(data.match_id, cues, languages)
    return PipelineResult([c.moment for c in contexts], track, trace, contexts)


async def _brief(
    stages: Stages, end: Any, done: list[MomentContext], data: MatchData, stats: StatsEngine
) -> list[dict[str, Any]]:
    names = {pid: p.short_name for pid, p in data.players.items()}
    names |= {tid: c.short_name for tid, c in data.clubs.items()}
    caller = stages.player.caller
    cue = await write_brief(
        caller, end, done, names, data.home_id, data.away_id, stats.context.score_at(end.t)
    )
    if cue is None:
        return []
    return [cue, *await stages.translator.translate(None, [cue], {})]


def _cue_track(match_id: str, raw: list[dict[str, Any]], languages: list[str]) -> CueTrack:
    def order(c: dict[str, Any]) -> tuple[Any, ...]:
        return (
            c["t_show"],
            LAYER_ORDER[Layer(c["layer"])],
            str(c["template"]),
            c.get("player_id") or "",
            c.get("team_id") or "",
            languages.index(c["lang"]) if c["lang"] in languages else 99,
        )

    cues = []
    for i, c in enumerate(sorted(raw, key=order)):
        clean = {k: v for k, v in c.items() if not k.startswith("_")}
        cues.append(Cue.model_validate(clean | {"cue_id": f"{match_id}-c{i + 1:03d}"}))
    present = [lang for lang in languages if any(c.lang == lang for c in cues)]
    return CueTrack(
        schema_version=SCHEMA_VERSION, match_id=match_id, languages=present or ["en"], cues=cues
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the MatchLens agents on one match.")
    parser.add_argument("match_dir", help="Folder with match.json, events.json, frames.jsonl ...")
    parser.add_argument("--out", default="out/match", help="Where to write the outputs")
    parser.add_argument("--lang", default="en,es", help="Comma-separated languages")
    parser.add_argument(
        "--engine", choices=["agent-framework", "asyncio"], default="agent-framework"
    )
    parser.add_argument(
        "--chaos",
        action="append",
        default=[],
        help="kill:<agent> or misquote:<agent>, e.g. kill:pundit; repeatable",
    )
    parser.add_argument("--timeout", type=float, default=None, help="Seconds per agent call")
    args = parser.parse_args(argv)

    configure_tracing()
    provider = provider_from_env(chaos=args.chaos)
    result = asyncio.run(
        run_match(
            args.match_dir,
            provider,
            languages=[x.strip() for x in args.lang.split(",") if x.strip()],
            engine=args.engine,
            timeout_s=args.timeout,
        )
    )
    result.write(args.out)
    summary = result.trace.statuses()
    print(
        f"{len(result.moments)} moments, {len(result.cues.cues)} cues "
        f"({', '.join(result.cues.languages)}) via {provider.name}; agent steps: {summary}"
    )
    print(f"Wrote {args.out}/moments.json, cues.json, agent_trace.json")


if __name__ == "__main__":  # pragma: no cover
    main()
