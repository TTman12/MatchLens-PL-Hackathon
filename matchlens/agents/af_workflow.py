"""Agent Framework executors for the moment workflow (see ``workflow.py``).

Kept apart from ``workflow.py`` because Agent Framework reads handler types from real
annotations, so this module must not use postponed annotations, and so that importing
the pipeline never requires the package.
"""

from typing import Any, Never

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

from .lenses import ClubLens, PlayerLens, PunditLens
from .state import MomentJob, MomentOutcome, VerifiedMoment
from .workflow import DirectedMoment, LensMessage, Stages, translate_stage, verify_stage


class Intake(Executor):
    """Receives a detected moment and hands it to the three lenses at once."""

    def __init__(self, stages: Stages) -> None:
        super().__init__(id="intake")
        self.stages = stages

    @handler
    async def receive(self, job: MomentJob, ctx: WorkflowContext[MomentJob]) -> None:
        m = job.ctx.moment
        self.stages.trace.add(
            m.moment_id,
            "detector",
            "moment-detector",
            "detect",
            "ok",
            f"{m.type} at {m.t_peak:g}s, importance {m.importance:g}",
        )
        await ctx.send_message(job)


class LensStep(Executor):
    def __init__(self, executor_id: str, lens: PlayerLens | ClubLens | PunditLens) -> None:
        super().__init__(id=executor_id)
        self.lens = lens

    @handler
    async def draft(self, job: MomentJob, ctx: WorkflowContext[LensMessage]) -> None:
        await ctx.send_message(LensMessage(job.ctx, await self.lens.run(job.ctx)))


class VerifyStep(Executor):
    """Fan-in: waits for all three lenses, then checks every draft against the evidence."""

    def __init__(self, stages: Stages) -> None:
        super().__init__(id="verifier")
        self.stages = stages

    @handler
    async def verify(
        self, messages: list[LensMessage], ctx: WorkflowContext[VerifiedMoment]
    ) -> None:
        moment = messages[0].ctx
        verified = await verify_stage(self.stages, moment, [m.output for m in messages])
        await ctx.send_message(verified)


class DirectStep(Executor):
    def __init__(self, stages: Stages) -> None:
        super().__init__(id="director")
        self.stages = stages

    @handler
    async def direct(self, vm: VerifiedMoment, ctx: WorkflowContext[DirectedMoment]) -> None:
        await ctx.send_message(DirectedMoment(vm, self.stages.director.schedule(vm)))


class TranslateStep(Executor):
    def __init__(self, stages: Stages) -> None:
        super().__init__(id="translator")
        self.stages = stages

    @handler
    async def translate(
        self, dm: DirectedMoment, ctx: WorkflowContext[Never, MomentOutcome]
    ) -> None:
        await ctx.yield_output(await translate_stage(self.stages, dm))


def build(stages: Stages, checkpoint_storage: Any | None = None) -> Any:
    intake = Intake(stages)
    lenses = [
        LensStep("player-lens", stages.player),
        LensStep("club-lens", stages.club),
        LensStep("pundit-lens", stages.pundit),
    ]
    verify, direct, translate = VerifyStep(stages), DirectStep(stages), TranslateStep(stages)
    builder = WorkflowBuilder(
        name="matchlens-moment", start_executor=intake, checkpoint_storage=checkpoint_storage
    )
    return (
        builder.add_fan_out_edges(intake, lenses)
        .add_fan_in_edges(lenses, verify)
        .add_edge(verify, direct)
        .add_edge(direct, translate)
        .build()
    )
