"""The Microsoft Agent Framework workflow that carries each moment from lenses to cues.

```
 moment ─▶ intake ─┬─▶ player lens (one agent per contributor) ─┐
                   ├─▶ club lens (per club, gated)              ├─▶ verifier ─▶ director
                   └─▶ pundit lens (gated)                      ┘       ─▶ translator ─▶ cues
```

The three lens executors run concurrently (an Agent Framework fan-out), and the
Verifier is a fan-in that waits for all three. Every executor reads and writes the same
``MomentContext``: the shared state the build plan calls the moment record. The workflow
is built once and run once per moment, in match order, so the Director's budget and
cooldown carry from one moment to the next. Checkpoint storage is optional; with it, a
crashed worker resumes a moment from the last completed step.

``PlainRunner`` runs the same stages with ``asyncio`` alone, for environments where the
Agent Framework package is unavailable. Both produce identical output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from matchlens.contracts import MomentStatus

from .director import Director
from .lenses import ClubLens, PlayerLens, PunditLens
from .state import LensOutput, MomentContext, MomentJob, MomentOutcome, VerifiedMoment
from .trace import AgentTrace
from .translator import Translator
from .verifier import Verifier


@dataclass
class Stages:
    player: PlayerLens
    club: ClubLens
    pundit: PunditLens
    verifier: Verifier
    director: Director
    translator: Translator
    trace: AgentTrace


@dataclass
class LensMessage:
    ctx: MomentContext
    output: LensOutput


@dataclass
class DirectedMoment:
    verified: VerifiedMoment
    cues: list[dict[str, Any]]


async def verify_stage(
    stages: Stages, ctx: MomentContext, outputs: list[LensOutput]
) -> VerifiedMoment:
    ctx.moment.status = MomentStatus.DRAFTED
    results = [r for out in sorted(outputs, key=lambda o: str(o.lens)) for r in out.results]
    approved = await stages.verifier.verify(ctx, results)
    ctx.moment.status = MomentStatus.VERIFIED
    return VerifiedMoment(ctx, approved)


async def translate_stage(stages: Stages, directed: DirectedMoment) -> MomentOutcome:
    vm = directed.verified
    extra = await stages.translator.translate(vm.ctx, directed.cues, vm.results)
    return MomentOutcome(vm.ctx, directed.cues + extra)


class PlainRunner:
    """The workflow's stages in order, with the lenses run concurrently by asyncio."""

    name = "asyncio"

    def __init__(self, stages: Stages) -> None:
        self.stages = stages

    async def run(self, job: MomentJob) -> MomentOutcome:
        import asyncio

        s = self.stages
        m = job.ctx.moment
        s.trace.add(
            m.moment_id,
            "detector",
            "moment-detector",
            "detect",
            "ok",
            f"{m.type} at {m.t_peak:g}s, importance {m.importance:g}",
        )
        outputs = await asyncio.gather(
            s.player.run(job.ctx), s.club.run(job.ctx), s.pundit.run(job.ctx)
        )
        vm = await verify_stage(s, job.ctx, list(outputs))
        return await translate_stage(s, DirectedMoment(vm, s.director.schedule(vm)))


def build_workflow(stages: Stages, checkpoint_storage: Any | None = None) -> Any:
    """The Agent Framework workflow for one moment. Agent Framework is imported lazily."""
    from .af_workflow import build

    return build(stages, checkpoint_storage)


class AgentFrameworkRunner:
    """Runs each moment through the Agent Framework workflow."""

    name = "agent-framework"

    def __init__(self, stages: Stages, checkpoint_storage: Any | None = None) -> None:
        self.workflow = build_workflow(stages, checkpoint_storage)

    async def run(self, job: MomentJob) -> MomentOutcome:
        result = await self.workflow.run(job)
        outputs = result.get_outputs()
        if len(outputs) != 1 or not isinstance(outputs[0], MomentOutcome):
            raise RuntimeError(f"workflow produced {outputs!r} for {job.ctx.moment_id}")
        return outputs[0]
