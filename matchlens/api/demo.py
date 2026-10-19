"""Build the demo match end to end: simulate the featured fixture, then run the agents.

    matchlens-demo                                   # data/demo, comeback storyline, offline
    matchlens-demo --storyline late_winner --out out/late
    MATCHLENS_PROVIDER=foundry matchlens-demo         # the same with agents on Foundry

The folder it writes has every file the web player reads (``match.json``,
``league.json``, ``events.json``, ``frames.jsonl``, ``cues.json``, ``moments.json``) plus
``season.json`` and ``agent_trace.json``, so ``web/`` plays it with
``?data=/data/demo/`` and ``matchlens-live`` streams it. Frames are about 45 MB, so
``data/demo`` is not committed; this rebuilds it in about 15 seconds.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from matchlens.agents.pipeline import run_match
from matchlens.agents.providers import configure_tracing, provider_from_env
from matchlens.sim.cli import main as sim_main

SEASON_DIR = Path("data/season")
STORYLINE = "comeback"


def build_demo(
    out: Path,
    *,
    season_dir: Path = SEASON_DIR,
    storyline: str = STORYLINE,
    agents: bool = True,
    languages: list[str] | None = None,
    chaos: list[str] | None = None,
) -> None:
    """Simulates the season's featured match into ``out`` and, with ``agents``, writes
    its moments, cues and agent trace next to it."""
    started = time.perf_counter()
    args = ["featured", "--season-dir", str(season_dir), "--out", str(out)]
    if storyline:
        args += ["--storyline", storyline]
    sim_main(args)
    print(f"Simulated in {time.perf_counter() - started:.1f}s")
    if not agents:
        return
    started = time.perf_counter()
    provider = provider_from_env(chaos=chaos or [])
    result = asyncio.run(run_match(out, provider, languages=languages or ["en", "es"]))
    result.write(out)
    print(
        f"{len(result.moments)} moments, {len(result.cues.cues)} cues via {provider.name} "
        f"in {time.perf_counter() - started:.1f}s"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Simulate the featured match and run the agents.")
    parser.add_argument("--out", type=Path, default=Path("data/demo"))
    parser.add_argument("--season-dir", type=Path, default=SEASON_DIR)
    parser.add_argument(
        "--storyline", default=STORYLINE, help="comeback, red_card, late_winner, a JSON file, or ''"
    )
    parser.add_argument("--lang", default="en,es", help="Comma-separated languages")
    parser.add_argument("--chaos", action="append", default=[], help="e.g. kill:pundit")
    parser.add_argument("--no-agents", action="store_true", help="Simulate only")
    args = parser.parse_args(argv)

    configure_tracing()
    build_demo(
        args.out,
        season_dir=args.season_dir,
        storyline=args.storyline,
        agents=not args.no_agents,
        languages=[x.strip() for x in args.lang.split(",") if x.strip()],
        chaos=args.chaos,
    )
    print("Watch it: cd web && npm run dev, then open http://localhost:5173/?data=/data/demo/")


if __name__ == "__main__":  # pragma: no cover
    main()
