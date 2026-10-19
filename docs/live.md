# Live: one match on a broadcast delay

`matchlens-live` ([matchlens/api/live.py](../matchlens/api/live.py)) streams one match to
every viewer on one shared clock, with the agent pipeline running inside the delay. The
web player follows it with `?live`.

```bash
matchlens-demo                     # build data/demo (simulate, then run the agents)
matchlens-live --web web/dist      # http://127.0.0.1:8000/?live
# or, while working on the player:
matchlens-live                     # feed on :8000
cd web && npm run dev              # http://localhost:5173/?live (Vite forwards /live/)
```

Options: `--lead 180` (match seconds of delay), `--pace condensed|realtime`,
`--max-rate 30`, `--lang en,es`, `--loop 30` (start the match again 30 s after it ends,
for an always-on link). The live server runs the agents itself, so it needs only the
simulated files (`match.json`, `league.json`, `season.json`, `events.json`,
`frames.jsonl`); if the folder is empty it simulates the featured match first.

## Two hands on one clock

```
 match time ─────────────────────────────────────────────────────────────▶
            viewer time v                          head = v + lead
                 │◀────────── lead (3 match minutes) ──────────▶│
   viewers watch here       agents work on moments the head has passed
```

- The **head** is how far the match has been released. Browsers buffer frames and events
  up to it; the Moment Detector's moments go to the agents once the head is 10 s past a
  moment's end (the detector reads at most a few seconds after a moment, such as a shot
  after a corner).
- **Viewer time** is `lead` behind the head. Every browser sits there, so everyone sees
  the same moment at the same time. It starts when the first viewer connects.
- Agents work through moments in match order, so the Director's attention budget and
  cooldown carry over as they do in a batch run. A cue that is still late when viewers
  reach it is dropped and logged in the trace (`/live/trace`, `late_cues`); playback never
  waits for an agent. With the offline provider a whole match publishes exactly the cues
  `matchlens-agents` writes for it (`tests/test_live.py`).

The simulator has already played the whole match by the time the server starts (it runs
hundreds of times faster than real time), the way a real feed would exist ahead of a delayed
broadcast. Nothing past the head reaches a viewer or an agent, and the player hides moment
markers past the live edge, so the delay never spoils a goal.

## The condensed clock

Viewer time runs at up to 30× between moments and eases to real time about 12 match
seconds before every moment that matters: one the detector scores at 0.3 or more, or one
the Director gave a replay or a box. It stays at 1× through the build-up, the replay and
the fact box, then eases back up ([matchlens/api/clock.py](../matchlens/api/clock.py),
mirrored in [web/src/model/clock.ts](../web/src/model/clock.ts)). The speed depends only on
match time, so switching lens or favourite player never moves the clock. A moment is known
to the server three match minutes before viewers reach it, which is what lets the clock
slow down *before* a goal. The featured match takes about 16 minutes to watch;
`--pace realtime` plays it at 1× throughout.

In file mode (no `?live`), the player uses the same rule, and the speed menu also offers
fixed speeds.

## The feed

| Request | Returns |
|---|---|
| `GET /live/match.json`, `/live/league.json` | The match files |
| `GET /live/poll?frames=&events=&moments=&cues=` | The clock, and every frame, event, moment summary and cue past the counts given, up to the head (frames 3,000 at a time; `more` says when to ask again at once) |
| `GET /live/trace` | The agent timeline so far, with the count of late cues |
| `GET /healthz` | The clock, for a health probe |

The clock in each poll is `{v, head, rate, lead, pace, started, ended}`. Browsers poll
twice a second and extrapolate `v` at `rate` between polls.
