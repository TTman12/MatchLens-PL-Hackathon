# MatchLens

[![CI](https://github.com/ttman12/matchlens-pl-hackathon/actions/workflows/ci.yml/badge.svg)](https://github.com/ttman12/matchlens-pl-hackathon/actions/workflows/ci.yml)

**Every moment, explained by why it matters, to you.**

MatchLens is a streaming-style match player for synthetic football. A seeded simulator
plays a match in a fictional league and streams tracking data and events. A team of
specialist agents, built on Microsoft Agent Framework with models, tracing and evaluations
in Microsoft Foundry, watches that stream inside a broadcast delay. They decide which
moments matter to *this* viewer's lens (a favourite player, a club, or the neutral
pundit), cut to a replay from the right camera angle, and show a short fact box in which
every number is checked against the evidence. The same intelligence reaches a casual fan
as a sentence and an analyst as the numbers behind it, in their language, and leaves the
pipeline as timed, machine-readable overlay cues a broadcast graphics engine could render.

> Status: early build for the Microsoft Premier League Hackathon (October 2026). The shared
> contracts and a hand-made sample match are in place; the simulator, agents and player are
> being built on top of them.

## How it works

| Stage | What happens | Where |
|---|---|---|
| Ingest | Simulator emits events and 10 Hz tracking frames | `matchlens/sim` |
| Interpret | Deterministic stats: pass difficulty, speeds, xG, win probability, momentum | `matchlens/stats` |
| Explain | Moment Detector, then Player, Club and Pundit agents, checked by a Verifier | `matchlens/agents` |
| Render | Director schedules replays and fact boxes as timed overlay cues | `matchlens/agents`, `web/` |
| Personalise | Lens, favourite player or club, depth (casual or analyst) and language | `web/`, Translator agent |
| Stream | One shared clock on a broadcast delay; agents work inside it | `matchlens/api` |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full flow and who owns what, and
[docs/contracts.md](docs/contracts.md) for the data formats every part shares.

## Repository layout

```
matchlens/
  contracts/   typed contracts (Pydantic): the source of truth for every data format
  sim/         simulator, season generator, calibration
  stats/       deterministic metrics and win probability
  mcp_server/  Match-State MCP server
  agents/      Agent Framework workflow, prompts, verifier, director
  api/         session API and streaming
web/           React + three.js player
schemas/       JSON Schemas generated from matchlens/contracts
data/          sample match, published synthetic season, featured match seeds
scripts/       one-off generators, e.g. the sample match
infra/         Azure deployment templates
evals/         Foundry groundedness evaluation set
docs/          architecture, contracts, calibration report
tests/         pytest suite
```

## Watch a whole match

Requires Python 3.11 or later and Node 20 or later. From the repository root:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[live]"
matchlens-demo                     # simulate the featured match, run the agents (~15 s)
(cd web && npm install && npm run build)
matchlens-live --web web/dist      # then open http://127.0.0.1:8000/?live
```

`matchlens-demo` plays the season's featured fixture with the `comeback` storyline
(Ashmere 3-2 Brackenford) into `data/demo/` and runs every agent on it with the offline
provider, which needs no credentials. `matchlens-live` streams that match on a three-minute
broadcast delay: the agents get each moment once the server's clock is past it and write
its cues while viewers are still watching the build-up. The player follows the shared
clock on the condensed timeline (fast between moments, real time for every moment that
matters), so a whole match takes about 15 minutes. Switch lens, favourite player, club or
language at any time; rewind behind the live edge and press "Go live" to catch up. See
[docs/live.md](docs/live.md).

Without the server, `cd web && npm run dev` plays `data/demo/` from files at
http://localhost:5173 (or the bundled sample if the demo has not been built), with the same
condensed clock and a free scrubber. To run the agents on Microsoft Foundry instead, install `.[foundry]`
and set the environment variables listed in [.env.example](.env.example).

## Quick start

Requires Python 3.11 or later.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # contracts and sample match
ruff check . && mypy      # lint and type check
```

Simulate a full match (events, 10 Hz tracking frames and metadata, validated against the
contracts) or a whole season with `matchlens-sim`; see [docs/simulator.md](docs/simulator.md)
and the [calibration report](docs/calibration.md):

```bash
matchlens-sim match --storyline comeback --out out/comeback
```

The sample match lives in [data/sample](data/sample): three minutes of a fictional derby
with a goal, a corner and a yellow card, as events, tracking frames, example moments and a
cue track. Rebuild it with `python scripts/make_sample_match.py`.

## A fictional universe

All clubs, players, stadiums and matches are invented and generated. MatchLens uses no real
league, club or player data, names or marks.

## Licence

[MIT](LICENSE)
