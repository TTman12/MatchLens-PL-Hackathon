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


class MatchRun:
    """The agent pipeline for one match, fed one moment at a time in match order.

    ``run_match`` drives it over a whole match at once; the live server
    (``matchlens.api.live``) drives it as its clock reaches each moment, so the agents
    only ever see moments the broadcast has already passed.
    """

    def __init__(
        self,
        data: MatchData,
        provider: ModelProvider | None = None,
        *,
        languages: list[str] | None = None,
        engine: Engine = "agent-framework",
        timeout_s: float | None = None,
        director: DirectorConfig | None = None,
    ) -> None:
        self.data = data
        self.provider = provider or OfflineProvider()
        languages = languages or ["en", "es"]
        if "en" not in languages:
            languages = ["en", *languages]
        self.languages = languages
        timeout = (
            timeout_s
            if timeout_s is not None
            else (5.0 if self.provider.name == "offline" else 20.0)
        )

        self.stats = StatsEngine(data)
        self.store = MatchStateStore(self.stats)
        self.trace = AgentTrace(provider=self.provider.name)
        self.stages = build_stages(
            self.stats,
            self.store,
            self.provider,
            self.trace,
            languages,
            timeout_s=timeout,
            director=director,
        )
        self.runner: AgentFrameworkRunner | PlainRunner
        try:
            self.runner = (
                AgentFrameworkRunner(self.stages)
                if engine == "agent-framework"
                else PlainRunner(self.stages)
            )
        except ImportError:
            self.trace.add(
                None,
                "pipeline",
                "pipeline",
                "start",
                "degraded",
                "agent-framework not installed: running stages with asyncio",
            )
            self.runner = PlainRunner(self.stages)
        self.done: list[MomentContext] = []
        self._period_ends = [e for e in data.events if e.type is EventType.PERIOD_END]

    def detect(self) -> list[MomentContext]:
        """Every candidate moment in the match, in match order."""
        return detect_moments(self.stats)

    async def until(self, t: float) -> list[dict[str, Any]]:
        """Briefs for every period that ended before match time ``t``."""
        cues: list[dict[str, Any]] = []
        for end in [e for e in self._period_ends if e.t < t]:
            cues += await _brief(self.stages, end, self.done, self.data, self.stats)
            self._period_ends.remove(end)
        return cues

    async def moment(self, ctx: MomentContext) -> list[dict[str, Any]]:
        """Runs one moment through the workflow, after any brief that falls before it."""
        cues = await self.until(ctx.moment.t_peak)
        self.store.add_moment(ctx.moment)
        outcome = await self.runner.run(MomentJob(ctx))
        self.done.append(ctx)
        return cues + outcome.cues

    async def finish(self) -> list[dict[str, Any]]:
        """Briefs for any period ends after the last moment."""
        return await self.until(float("inf"))


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
    run = MatchRun(
        data, provider, languages=languages, engine=engine, timeout_s=timeout_s, director=director
    )
    contexts = run.detect()
    cues: list[dict[str, Any]] = []
    for ctx in contexts:
        cues += await run.moment(ctx)
    cues += await run.finish()
    track = cue_track(data.match_id, cues, run.languages)
    return PipelineResult([c.moment for c in contexts], track, run.trace, contexts)


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


def cue_track(match_id: str, raw: list[dict[str, Any]], languages: list[str]) -> CueTrack:
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
