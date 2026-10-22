"""swing-live: the live site. Serves the broadcast screen (web/) and generates brand-new matches
on request, played through the agents as unseen matches (job.py).

    swing-live --web web --port 8000                  # what the container runs
    swing-live --web web --agents offline             # no Azure: the rules explain every match

    POST /api/generate        start a new match            -> 202 {id, seed, home, away, agents, note}
         ?drill=<agent>[&drill_mode=down|flaky]   ... with that agent knocked out (the admin
                              screen's fault drill, failover.py)
    GET  /api/live/<id>       the screen's bundle so far   (bundle.live says how far the feed has got)
    GET  /api/live            today's budget               -> {ai_matches_left, ...}
    GET  /healthz             for the Container Apps probes

Settings (environment):

- AZURE_AI_PROJECT_ENDPOINT, AZURE_AI_MODEL: the Foundry project the agents run on. The container
  app signs in with its managed identity (DefaultAzureCredential).
- SWING_LIVE_AGENTS: foundry (the default when the endpoint is set) or offline.
- SWING_DAILY_AI_MATCHES (10) and SWING_DAILY_MODEL_CALLS (1700): today's budget. Past it,
  matches are explained by the rules, and the screen says so.
- SWING_GENERATE_PER_HOUR (6): new matches a visitor may start an hour.
- SWING_DRILLS (on) and SWING_DRILLS_PER_HOUR (3): the fault drill. A drill only affects the
  match it starts, costs no model calls and needs no key; `off` refuses it.
- SWING_STATE_DIR (/tmp/swing): where the day's budget is kept.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import secrets
import threading
import time
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..agents.runners import ENDPOINT_VAR, Runner
from .failover import Drill
from .job import Job, pick_fixture
from .limits import DailyBudget, RateLimit

log = logging.getLogger("swing.live")

MAX_RUNNING = 3  # matches being played at once (each is light; the agents are the slow part)
MAX_AI_RUNNING = 1  # matches the agents explain at once
KEEP = 45 * 60  # seconds a finished match stays available
MAX_KEPT = 30
PREFLIGHT_TIMEOUT = 20.0


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Live:
    """The matches being played, the budget and the rate limit. Matches run on one asyncio loop in a
    background thread; the HTTP threads only read their published snapshots."""

    def __init__(
        self,
        agents: str,
        budget: DailyBudget,
        limit: RateLimit,
        pace: float | None = None,
        drills: RateLimit | None = None,
    ) -> None:
        self.agents = agents
        self.budget = budget
        self.limit = limit
        self.pace = pace
        self.drills = drills  # None: the fault drill is off
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._rng = random.Random(secrets.randbits(64))
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="swing-live", daemon=True).start()

    def _prune(self) -> None:
        now = time.time()
        for k, j in list(self.jobs.items()):
            if j.status in ("done", "failed") and now - j.created > KEEP:
                del self.jobs[k]
        while len(self.jobs) > MAX_KEPT:
            oldest = min((j for j in self.jobs.values() if j.status in ("done", "failed")), key=lambda j: j.created, default=None)
            if oldest is None:
                break
            del self.jobs[oldest.id]

    def running(self) -> list[Job]:
        return [j for j in self.jobs.values() if j.status in ("generating", "playing")]

    def generate(self, visitor: str, drill: Drill | None = None) -> tuple[int, dict[str, Any]]:
        if drill is not None:
            if self.drills is None:
                return 403, {"error": "The fault drill is switched off on this server."}
            wait = self.drills.allow(visitor)
            if wait:
                minutes = max(1, round(wait / 60))
                busy = f"You have run a lot of fault drills. Try again in about {minutes} min."
                return 429, {"error": busy, "retry_after": wait}
        wait = self.limit.allow(visitor)
        if wait:
            minutes = max(1, round(wait / 60))
            return 429, {"error": f"You have generated a lot of matches. Try again in about {minutes} min.", "retry_after": wait}
        with self._lock:
            self._prune()
            running = self.running()
            if len(running) >= MAX_RUNNING:
                busy = "The match engine is busy with other viewers' matches. Try again in a minute."
                return 503, {"error": busy, "retry_after": 60}
            home, away, seed = pick_fixture(self._rng)
            job = Job(id=secrets.token_urlsafe(6), home=home, away=away, seed=seed, budget=self.budget, drill=drill)
            if self.pace is not None:
                job.pace = self.pace
            if self.agents != "foundry":
                job.note = "This server runs without the AI agents, so the rules write the cards."
            elif sum(j.agents_on for j in running) >= MAX_AI_RUNNING:
                job.note = "The AI agents are busy with another viewer's match, so the rules write this one's cards."
            elif not self.budget.start_match():
                job.note = "Today's AI matches are used up, so the rules write this one's cards. The agents are back tomorrow."
            else:
                job.foundry = self._foundry()
                if job.foundry is None:
                    job.note = "Foundry could not be reached, so the rules write this match's cards."
            self.jobs[job.id] = job
        asyncio.run_coroutine_threadsafe(self._run(job), self.loop)
        agents = "foundry" if job.agents_on else "rules"
        out = {"id": job.id, "seed": seed, "home": home, "away": away, "agents": agents, "note": job.note}
        return 202, out | ({"drill": drill.as_dict()} if drill else {})

    def _foundry(self) -> Runner | None:
        try:
            from ..agents.runners import FoundryRunner

            return FoundryRunner(concurrency=6, timeout=30)
        except Exception as exc:
            log.warning("no Foundry runner: %s", exc)
            return None

    async def _run(self, job: Job) -> None:
        if job.foundry is not None and not await self._preflight(job.foundry):
            await job.foundry.close()
            job.foundry = None
            job.note = "Foundry could not be reached, so the rules write this match's cards."
        await job.run()

    async def _preflight(self, runner: Runner) -> bool:
        """Can the app sign in to Foundry? Checked once per match, so a missing role or endpoint costs
        seconds, not a minute of retries on the first moment."""
        cred = getattr(runner, "_credential", None)
        if cred is None:
            return True
        try:
            await asyncio.wait_for(cred.get_token("https://ai.azure.com/.default"), PREFLIGHT_TIMEOUT)
            return True
        except Exception as exc:
            log.warning("Foundry sign-in failed: %s", exc)
            return False

    def status(self) -> dict[str, Any]:
        return {**self.budget.as_dict(), "agents": self.agents, "running": len(self.running()), "drills": self.drills is not None}


class Handler(SimpleHTTPRequestHandler):
    live: Live

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class's name
        if not self.path.startswith(("/api/live/", "/healthz")):  # polling would drown the log
            log.info("%s %s", self.address_string(), format % args)

    def _visitor(self) -> str:
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or self.client_address[0]

    def _json(self, code: int, obj: Any) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if code in (429, 503) and isinstance(obj, dict) and obj.get("retry_after"):
            self.send_header("Retry-After", str(int(obj["retry_after"]) + 1))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        if url.path != "/api/generate":
            self._json(404, {"error": "not found"})
            return
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            drill = Drill.parse(q.get("drill"), q.get("drill_mode"))
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        code, body = self.live.generate(self._visitor(), drill)
        self._json(code, body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/healthz":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/live":
            self._json(200, self.live.status())
        elif path.startswith("/api/live/"):
            self._snapshot(path.removeprefix("/api/live/"))
        else:
            super().do_GET()

    def _snapshot(self, job_id: str) -> None:
        job = self.live.jobs.get(job_id)
        if job is None:
            self._json(404, {"error": "That match has finished and been cleared away. Generate a new one."})
            return
        snap = job.snapshot
        if snap is None:
            self._json(200, {"live": job.info()})
            return
        etag = f'"{job_id}-{snap.version}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        gz = "gzip" in self.headers.get("Accept-Encoding", "")
        body = snap.gz if gz else snap.body
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(web: Path, port: int, live: Live, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    handler = type("LiveHandler", (Handler,), {"live": live})
    server = ThreadingHTTPServer((host, port), partial(handler, directory=str(web)))
    server.daemon_threads = True
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--web", type=Path, default=Path("web"))
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--agents", choices=["foundry", "offline"], help="default: foundry when the endpoint is set")
    ap.add_argument("--pace", type=float, help="seconds between feed minutes (default 0.5)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    agents = args.agents or os.environ.get("SWING_LIVE_AGENTS") or ("foundry" if os.environ.get(ENDPOINT_VAR) else "offline")
    state = Path(os.environ.get("SWING_STATE_DIR", "/tmp/swing"))
    budget = DailyBudget(state / "budget.json", _int("SWING_DAILY_AI_MATCHES", 10), _int("SWING_DAILY_MODEL_CALLS", 1700))
    drills = RateLimit(_int("SWING_DRILLS_PER_HOUR", 3), 3600) if os.environ.get("SWING_DRILLS", "on") != "off" else None
    live = Live(agents, budget, RateLimit(_int("SWING_GENERATE_PER_HOUR", 6), 3600), args.pace, drills)
    server = make_server(args.web, args.port, live, args.host)
    log.info("serving %s on :%d, agents %s, %s", args.web, args.port, agents, budget.as_dict())
    server.serve_forever()


if __name__ == "__main__":
    main()
