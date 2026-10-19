# Architecture and ownership

This note says how data flows through MatchLens and which part of the code each track
owns, so the tracks can build in parallel without editing the same files.

## Data flow

```
 Simulator (seeded) ──frames 10 Hz + events──▶ match state
      │                                            │
 Season generator ──▶ league.json, season.json     ▼
                                           Stats engine (deterministic)
                                           pass difficulty, speeds, xG,
                                           win probability, momentum
                                                   │
                                                   ▼
                                           Moment Detector ──▶ Moment (detected)
                                                   │
                     ┌─────────────────────────────┼─────────────────────────┐
                     ▼                             ▼                         ▼
               Player agent ×N               Club agent ×2              Pundit agent
               (each contributor)                  │                         │
                     └──────────────┬──────────────┴─────────────────────────┘
                                    ▼
                             Verifier ──▶ Moment (verified)
                                    ▼
                             Director ──▶ Moment (scheduled) + Cues
                                    ▼
                             Translator ──▶ Cues per language
                                    ▼
                    cue track + frames ──▶ browser player (renders at T − delay)
```

The server simulates ahead of the viewer. The browser plays frames behind it and shows
each cue when its playback clock reaches the cue's `t_show`. Agents run once per match,
not once per viewer; the browser holds every lens's cues and picks locally, so switching
lens or favourite player is instant.

## Who owns what

Three build tracks, plus the shared foundation. A track may freely change anything it
owns. To change something another track owns, open a PR and tag that track in it.

| Area | Owner | Produces | Reads |
|---|---|---|---|
| `matchlens/contracts/`, `schemas/` | Foundation (shared) | The data formats | — |
| `scripts/make_sample_match.py`, `data/sample/` | Foundation (shared) | Sample match for every track | contracts |
| `matchlens/sim/` | SIM | `events.json`, `frames.jsonl`, `match.json`, `league.json`, `season.json` | contracts |
| `data/` (except `sample/`) | SIM | Published season dataset, featured match seeds | — |
| `docs/calibration.md` | SIM | Calibration report | sim output |
| `matchlens/stats/` | AGT | Derived stats and win probability, as functions | events, frames, season |
| `matchlens/mcp_server/` | AGT | Match-State MCP tools | stats, season, moments |
| `matchlens/agents/` | AGT | `moments.json`, `cues.json` | events, frames, season, MCP tools |
| `matchlens/api/` | AGT | Session API, frame and cue streams | sim, agents |
| `evals/` | AGT | Groundedness evaluation set and results | moments |
| `web/` | WEB | The player | `frames.jsonl`, `cues.json`, `match.json`, `league.json`, `schemas/` |
| `infra/`, `.github/workflows/deploy*.yml` | AGT, until someone else takes it | Azure deployment | — |
| `README.md`, `docs/ARCHITECTURE.md` | Shared | — | — |

`.github/workflows/ci.yml` is shared: add a job for your track (for example a web build)
rather than editing another track's steps.

## The seams between tracks

- **SIM to everyone.** The simulator writes the same files the sample match has, in the
  same formats. Until it exists, build against `data/sample/`.
- **AGT to WEB.** The web player needs only `frames.jsonl`, `cues.json`, `match.json` and
  `league.json`. It never calls an agent. A live run streams the same objects.
- **Stats to agents.** Every number an agent writes comes from an evidence item on the
  moment, and every evidence item comes from the stats engine or season data, never from a
  model. The Verifier enforces this.

## Changing a contract

Contracts are the one place parallel work can collide, so:

1. Change the model in `matchlens/contracts/` in a PR of its own, or as the first commit of
   your PR with a title that says so.
2. Run `matchlens-schemas` to regenerate `schemas/`, and `python scripts/make_sample_match.py`
   if the sample is affected. CI fails if either is stale.
3. Adding an optional field is safe. Renaming or removing a field, or making one required,
   is breaking: bump `SCHEMA_VERSION` and say in the PR which readers need updating.
4. `Qualifiers` on events accepts extra keys, so the simulator can add detail without a
   contract change. Promote a key to a named field once another module depends on it.
