"""Shared, cached objects for the agents-track tests (stats, moments, pipeline runs)."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from functools import cache
from types import ModuleType

from matchlens.agents.detector import detect_moments
from matchlens.agents.pipeline import PipelineResult, run_match
from matchlens.agents.providers import ChaosProvider, OfflineProvider
from matchlens.agents.state import MomentContext
from matchlens.stats import StatsEngine, load_match

from .conftest import ROOT, SAMPLE


@cache
def stats() -> StatsEngine:
    return StatsEngine(load_match(SAMPLE))


def moments() -> dict[str, MomentContext]:
    """Fresh detector output for the sample, keyed by moment type."""
    return {str(c.moment.type): c for c in detect_moments(StatsEngine(load_match(SAMPLE)))}


@cache
def run(*chaos: str, engine: str = "agent-framework") -> PipelineResult:
    provider = (
        ChaosProvider.from_rules(OfflineProvider(), list(chaos)) if chaos else OfflineProvider()
    )
    return asyncio.run(run_match(SAMPLE, provider, languages=["en", "es"], engine=engine))  # type: ignore[arg-type]


@cache
def evals_module() -> ModuleType:
    path = ROOT / "evals" / "run_evals.py"
    spec = importlib.util.spec_from_file_location("run_evals", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
