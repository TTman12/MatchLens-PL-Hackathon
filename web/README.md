# web

The MatchLens player: a streaming-style match viewer built with React, Vite, TypeScript
and three.js. Owned by the WEB track.

```bash
cd web
npm install
npm run dev        # http://localhost:5173, plays data/sample/
npm test           # model tests, plus the sample data checked against schemas/
npm run build      # static site in dist/, with the sample match copied in
```

`?data=<url>/` plays any folder laid out like `data/sample/` (`match.json`, `league.json`,
`events.json`, `cues.json`, `frames.jsonl`), so simulator output needs no code change.
`?t=<seconds>` opens at a moment. Shortcuts: space, ← →, N (next moment), 1 to 3 (lens),
F (full screen), M (mute).

## How it works

The browser gets every frame and every cue for the match, then decides locally what this
viewer sees. Nothing is generated per viewer, so switching lens, favourite player, club or
language is instant, even mid-replay.

| Folder | What it does |
|---|---|
| `src/contracts/` | Types generated from `schemas/` (`npm run gen:types`; CI fails if stale). The player reads data only through these |
| `src/model/` | Pure logic, no rendering: tracking data in typed arrays, cue selection per viewer, the one-box-at-a-time schedule, replay timing, and trails and peak speeds for all 22 players in every replay window |
| `src/player/engine.ts` | The client-side director: playback clock, replay and camera choice each frame, and what each lens draws |
| `src/render/` | three.js stadium, players, ball, trails and the camera presets (`tv_main`, `spidercam_goal`, `corner_low`, `card_close`, `save_reverse`, `tactical_high`) |
| `src/ui/` | The shell: score bug, replay bug, name tags, speedometer, fact boxes with the evidence dropdown, lens sweep, controls and sidebars |

### Rules it follows from the contracts

- **Cues** show when playback reaches `t_show`, for `duration` seconds. `global` cues go
  to everyone; `player`, `club` and `pundit` cues go to viewers on that lens whose
  favourite matches `player_id` or `team_id`. Each cue appears in the viewer's language,
  falling back to English.
- **One box at a time.** Boxes queue behind the one on screen and are dropped if they
  would be more than 6 seconds late (`MAX_BOX_DELAY_S`).
- **Replays** take over the screen from `t_show` for `duration`. When the window doesn't
  fit at `replay_speed`, the build-up plays quick and the end of the move plays slowed.
  The Player lens uses that player's replay cue (highlight, trail, speedometer); anyone
  else gets the global one. A favourite who had no part gets a "not involved" line, as
  the contracts ask the browser to generate.
- **Live camera.** The main camera follows the ball; set pieces cut to the corner camera
  from the events. The camera menu can force any preset, for testing and demos.

Audio is a crowd bed synthesised with Web Audio, so there's no recorded or copyrighted
sound.
