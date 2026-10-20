"""The live server: one match on a broadcast delay, with the agents working inside it.

    matchlens-live                       # featured match from data/demo, offline agents
    matchlens-live out/comeback --lead 120 --pace realtime
    matchlens-live --web web/dist        # also serve the built player on the same port

The match has already been simulated (the simulator runs far faster than real time), but
nothing reaches viewers or agents until the server's clock gets there. The clock has two
hands:

- the **head**, the latest match time released to the agents and buffered to browsers;
- the **viewer time**, ``lead`` match seconds behind the head, which every browser shows.

A moment goes to the agents once the head is a few seconds past it (the detector reads
at most a few seconds after a moment, such as a shot after a corner), so its cues are
written while viewers are still watching the build-up to it, the way a broadcast delay
gives a graphics team time. A cue that is still late when viewers reach it is dropped
and logged; the stream never waits for an agent.

Viewer time runs on the condensed clock (``matchlens.api.clock``) or at real time with
``--pace realtime``. It starts when the first viewer connects, and is shared: every
viewer polls the same clock.

Browsers poll ``GET /live/poll``, passing how many frames, events, moments and cues they
already hold, and get the rest up to the head plus the clock. ``/live/match.json`` and
``/live/league.json`` are the match files; ``/live/trace`` is the agent timeline so far.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import contextlib
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from matchlens.agents.pipeline import MatchRun, cue_track
from matchlens.agents.providers import (
    BlobReplayStore,
    ModelProvider,
    OfflineProvider,
    ReplayProvider,
    close_provider,
    configure_tracing,
    provider_from_env,
)
from matchlens.agents.state import MomentContext
from matchlens.contracts import EventType
from matchlens.stats import MatchData, load_match

from .clock import MAX_RATE, Span, rate_at, slow_spans

log = logging.getLogger("matchlens.live")

Pace = Literal["condensed", "realtime"]
LEAD_S = 180.0
"""Match seconds the head runs ahead of viewers: about three match minutes."""
SETTLE_S = 10.0
"""How far past a moment's end the head must be before the moment goes to the agents."""
TICK_S = 0.05
MAX_FRAMES_PER_POLL = 3000
MOMENT_FIELDS = (
    "moment_id",
    "type",
    "period",
    "t_start",
    "t_peak",
    "t_end",
    "replay_window",
    "importance",
)


@dataclass
class Released:
    """What has been released to viewers so far, in the order it was released."""

    moments: list[dict[str, Any]] = field(default_factory=list)
    cues: list[dict[str, Any]] = field(default_factory=list)
    late: int = 0


BUDGET_VAR = "MATCHLENS_DAILY_MODEL_CALLS"
"""Most agent tasks a day that may reach the model; past it, unseen tasks use templates."""
REPLAY_BLOB_VAR = "MATCHLENS_REPLAY_BLOB_URL"
"""Azure blob that keeps remembered answers and today's count across restarts."""


def replay_from_env(provider: ModelProvider, env: Mapping[str, str] | None = None) -> ModelProvider:
    """Wrap a model provider for replay, with the budget and store the environment names."""
    if isinstance(provider, OfflineProvider):
        return provider
    env = os.environ if env is None else env
    budget = env.get(BUDGET_VAR, "").strip()
    blob = env.get(REPLAY_BLOB_VAR, "").strip()
    return ReplayProvider(
        provider,
        daily_budget=int(budget) if budget else None,
        store=BlobReplayStore(blob) if blob else None,
    )


class LiveSession:
    """One match, one shared clock, and the agent pipeline running inside the delay."""

    def __init__(
        self,
        match_dir: Path,
        provider_factory: Any = None,
        *,
        lead_s: float = LEAD_S,
        pace: Pace = "condensed",
        max_rate: float = MAX_RATE,
        languages: list[str] | None = None,
    ) -> None:
        self.match_dir = match_dir
        self.data: MatchData = load_match(match_dir)
        self.meta_json = (match_dir / "match.json").read_bytes()
        self.league_json = (match_dir / "league.json").read_bytes()
        self.frame_lines, self.frame_times = _read_frames(match_dir / "frames.jsonl")
        self.events = [e.model_dump(mode="json", exclude_none=True) for e in self.data.events]
        self.start = self.frame_times[0]
        self.end = self.frame_times[-1]
        self.lead_s = lead_s
        self.pace = pace
        self.max_rate = max_rate
        self.languages = languages or ["en", "es"]
        if provider_factory is None:
            # One provider for every loop of the match: one Azure credential, and each
            # loop after the first replays the model's answers instead of paying again.
            shared = replay_from_env(provider_from_env())
            provider_factory = lambda: shared  # noqa: E731
        self._provider_factory = provider_factory
        self.jobs: asyncio.Queue[tuple[int, MomentContext | float]] = asyncio.Queue()
        self.generation = 0
        self.reset()

    def reset(self) -> None:
        """Back to kick-off, with fresh agents. Jobs queued for the old run are skipped."""
        self.generation += 1
        provider: ModelProvider = self._provider_factory()
        self.provider = provider
        self.run = MatchRun(self.data, provider, languages=self.languages)
        self.pending: list[MomentContext] = self.run.detect()
        self.periods = [e.t for e in self.data.events if e.type is EventType.PERIOD_END]
        self.released = Released()
        self.spans: list[Span] = []
        self.v = self.start
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self._next_cue = 1

    # -- the clock -------------------------------------------------------------------------

    @property
    def head(self) -> float:
        return min(self.end, self.v + self.lead_s)

    @property
    def rate(self) -> float:
        if self.started_at is None or self.ended_at is not None:
            return 0.0
        return 1.0 if self.pace == "realtime" else rate_at(self.v, self.spans, self.max_rate)

    def start_clock(self) -> None:
        if self.started_at is None:
            self.started_at = time.monotonic()
            self._dispatch()

    def advance(self, dt: float) -> None:
        """Moves viewer time on by ``dt`` wall seconds and releases what the head passed."""
        if self.started_at is None or self.ended_at is not None:
            return
        self.v = min(self.end, self.v + dt * self.rate)
        if self.v >= self.end:
            self.ended_at = time.monotonic()
        self._dispatch()

    def _dispatch(self) -> None:
        head = self.head
        while self.pending and self.pending[0].moment.t_end + SETTLE_S <= head:
            ctx = self.pending.pop(0)
            self.released.moments.append(_summary(ctx))
            self.jobs.put_nowait((self.generation, ctx))
        while self.periods and self.periods[0] <= head:
            self.jobs.put_nowait((self.generation, self.periods.pop(0) + 0.01))
        self.spans = slow_spans(self.released.moments, self.released.cues)

    # -- the agents ------------------------------------------------------------------------

    async def agents(self) -> None:
        """Works through released moments in match order, so the Director's budget and
        cooldown carry from one moment to the next."""
        while True:
            await self._work(await self.jobs.get())

    async def drain(self) -> None:
        """Runs every job queued so far, now. For tests, which drive the clock by hand."""
        while not self.jobs.empty():
            await self._work(self.jobs.get_nowait())

    async def _work(self, item: tuple[int, MomentContext | float]) -> None:
        generation, job = item
        if generation != self.generation:
            return
        try:
            raw = await (self.run.until(job) if isinstance(job, float) else self.run.moment(job))
        except Exception:
            log.exception("agent pipeline failed on %s", job)
            return
        if generation == self.generation:
            self._publish(raw)

    def _publish(self, raw: list[dict[str, Any]]) -> None:
        if not raw:
            return
        track = cue_track(self.data.match_id, raw, self.run.languages)
        for cue in track.cues:
            c = cue.model_dump(mode="json", exclude_none=True)
            if c["t_show"] + c["duration"] < self.v or c["t_show"] < self.v - 1.0:
                self.released.late += 1
                self.run.trace.add(
                    c.get("moment_id"),
                    "director",
                    "live",
                    "publish",
                    "cut",
                    f"{c['template']} cue for {c['t_show']:g}s arrived after viewers passed it",
                )
                continue
            c["cue_id"] = f"{self.data.match_id}-L{self._next_cue:04d}"
            self._next_cue += 1
            self.released.cues.append(c)
        self.spans = slow_spans(self.released.moments, self.released.cues)

    # -- what viewers get ------------------------------------------------------------------

    def clock(self) -> dict[str, Any]:
        return {
            "v": round(self.v, 3),
            "head": round(self.head, 3),
            "rate": round(self.rate, 4),
            "lead": self.lead_s,
            "pace": self.pace,
            "started": self.started_at is not None,
            "ended": self.ended_at is not None,
            "end": self.end if self.ended_at is not None else None,
        }

    def poll(self, frames: int, events: int, moments: int, cues: int) -> str:
        """Everything a browser does not have yet, up to the head, as one JSON string."""
        self.start_clock()
        head = self.head
        upto = bisect.bisect_right(self.frame_times, head)
        stop = min(upto, frames + MAX_FRAMES_PER_POLL)
        new_events = [e for e in self.events[events:] if e["t"] <= head]
        body = {
            "clock": self.clock(),
            "events": new_events,
            "moments": self.released.moments[moments:],
            "cues": self.released.cues[cues:],
            "more": stop < upto,
            "languages": self.run.languages,
        }
        # Frames are passed through as the simulator wrote them, without re-encoding.
        frame_json = "[" + ",".join(self.frame_lines[frames:stop]) + "]"
        return json.dumps(body)[:-1] + ',"frames":' + frame_json + "}"

    def trace(self) -> dict[str, Any]:
        return self.run.trace.to_json() | {"late_cues": self.released.late}


def _summary(ctx: MomentContext) -> dict[str, Any]:
    m = ctx.moment.model_dump(mode="json")
    return {k: m[k] for k in MOMENT_FIELDS}


def _read_frames(path: Path) -> tuple[list[str], list[float]]:
    lines: list[str] = []
    times: list[float] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                lines.append(line)
                times.append(float(json.loads(line)["t"]))
    if len(lines) < 2:
        raise ValueError(f"{path} needs at least two frames")
    return lines, times


async def clock_loop(session: LiveSession, loop_after_s: float | None) -> None:
    last = time.monotonic()
    while True:
        await asyncio.sleep(TICK_S)
        now = time.monotonic()
        session.advance(now - last)
        last = now
        if (
            loop_after_s is not None
            and session.ended_at is not None
            and now - session.ended_at > loop_after_s
        ):
            log.info("match over; starting it again")
            session.reset()


def create_app(
    session: LiveSession, web_dir: Path | None = None, loop_after_s: float | None = None
) -> Any:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles

    def poll(request: Request) -> Response:
        q = request.query_params

        def n(key: str) -> int:
            try:
                return max(0, int(q.get(key, "0")))
            except ValueError:
                return 0

        body = session.poll(n("frames"), n("events"), n("moments"), n("cues"))
        return Response(body, media_type="application/json", headers=NO_STORE)

    def match_json(_: Request) -> Response:
        return Response(session.meta_json, media_type="application/json")

    def league_json(_: Request) -> Response:
        return Response(session.league_json, media_type="application/json")

    def trace(_: Request) -> Response:
        return JSONResponse(session.trace(), headers=NO_STORE)

    def health(_: Request) -> Response:
        return JSONResponse({"ok": True, "clock": session.clock()}, headers=NO_STORE)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        tasks = [
            asyncio.create_task(clock_loop(session, loop_after_s)),
            asyncio.create_task(session.agents()),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await close_provider(session.provider)

    routes: list[Any] = [
        Route("/live/poll", poll),
        Route("/live/match.json", match_json),
        Route("/live/league.json", league_json),
        Route("/live/trace", trace),
        Route("/healthz", health),
    ]
    if web_dir is not None:

        def home(request: Request) -> Response:
            # A bare link opens the live match; ?data= and the like still reach the player.
            if not request.query_params:
                return RedirectResponse("/?live", status_code=307)
            return FileResponse(web_dir / "index.html", headers=NO_STORE)

        routes += [Route("/", home), Mount("/", StaticFiles(directory=web_dir, html=True))]
    return Starlette(routes=routes, lifespan=lifespan)


NO_STORE = {"Cache-Control": "no-store"}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stream one match on a broadcast delay.")
    parser.add_argument(
        "match_dir",
        nargs="?",
        default="data/demo",
        help="Folder with match.json, league.json, season.json, events.json, frames.jsonl "
        "(default data/demo; built with matchlens-demo if missing)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--lead", type=float, default=LEAD_S, help="Match seconds of delay")
    parser.add_argument("--pace", choices=["condensed", "realtime"], default="condensed")
    parser.add_argument("--max-rate", type=float, default=MAX_RATE)
    parser.add_argument("--lang", default="en,es", help="Comma-separated languages")
    parser.add_argument("--web", type=Path, default=None, help="Serve this built player too")
    parser.add_argument(
        "--loop", type=float, default=None, help="Restart the match this many seconds after it ends"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    match_dir = Path(args.match_dir)
    if not (match_dir / "frames.jsonl").exists():
        from .demo import build_demo

        log.info("no match in %s yet; simulating the featured match there", match_dir)
        build_demo(match_dir, agents=False)

    import uvicorn

    configure_tracing()
    session = LiveSession(
        match_dir,
        lead_s=args.lead,
        pace=args.pace,
        max_rate=args.max_rate,
        languages=[x.strip() for x in args.lang.split(",") if x.strip()],
    )
    app = create_app(session, args.web, args.loop)
    where = f"http://{args.host}:{args.port}"
    print(f"MatchLens live: {session.data.match_id}, {args.pace} clock, {args.lead:g}s delay")
    print(f"  feed  {where}/live/poll")
    if args.web:
        print(f"  watch {where}/?live")
    else:
        print("  watch http://localhost:5173/?live  (cd web && npm run dev)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":  # pragma: no cover
    main()
