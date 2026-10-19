# Data contracts

Every data format MatchLens passes between modules is defined once, as a Pydantic model in
[`matchlens/contracts`](../matchlens/contracts). The JSON Schemas in [`schemas/`](../schemas)
are generated from those models for readers outside Python, such as the web player
(`npx json-schema-to-typescript` turns them into TypeScript types). Schema version:
`1.0.0`, in `SCHEMA_VERSION`.

| File | Contract | Schema | Written by |
|---|---|---|---|
| `league.json` | `League` | `league.schema.json` | Season generator |
| `season.json` | `Season` | `season.schema.json` | Season generator |
| `match.json` | `MatchMeta` | `match_meta.schema.json` | Simulator |
| `events.json` | list of `MatchEvent` | `match_event.schema.json` | Simulator |
| `frames.jsonl` | one `Frame` per line | `frame.schema.json` | Simulator |
| `moments.json` | list of `Moment` | `moment.schema.json` | Detector and agents |
| `cues.json` | `CueTrack` of `Cue` | `cue_track.schema.json`, `cue.schema.json` | Director and Translator |
| (inside a cue) | `FactBox` | `fact_box.schema.json` | Director |

All models reject unknown fields, except event `qualifiers`.

## Shared conventions

### Time

`t` is **match time in seconds since kick-off on one continuous timeline**. Period 2
starts where period 1 ended; the half-time break is not on the timeline. Frames, events,
moments and cues all use the same `t`, so a cue can be lined up with the frame it
belongs to without conversion. `clock` is the broadcast clock built by `format_clock`:
`12:34`, `45+2:14`, `90+1:01`.

### Coordinates

Metres on a 105 × 68 m pitch, in one of two frames (`matchlens/contracts/pitch.py`):

- **Pitch frame**, used by frames, pass maps and camera focus points. Fixed for the
  whole match. `x` runs from the left goal line to the right one as seen from the main
  TV camera; `y = 0` is the touchline nearest that camera; `z` is height.
- **Attacking frame**, used by events. Relative to the event's `team_id`: `x` runs from
  that team's own goal line (0) to the goal it attacks (105), and `y = 0` is the touchline
  on its right. Defensive events (tackle, interception, pressure, save) use the defending
  team's frame.

`match.json` says which way the home team attacks in period 1
(`home_attacks_in_period_1`); teams swap at half-time. Use `attacking_direction`,
`to_pitch` and `to_attacking` rather than converting by hand.

### Ids

| Id | Pattern | Example |
|---|---|---|
| match | `m` + digits | `m017` |
| team | three lowercase letters | `ash` |
| player | `<team>-<squad number>` | `ash-09` |
| event | `<match>-e` + 4+ digits | `m017-e0025` |
| possession | `<match>-p` + 3+ digits | `m017-p007` |
| moment | `<match>-mo` + 2+ digits | `m017-mo03` |
| cue | `<match>-c` + 3+ digits | `m017-c004` |
| evidence | `ev` + digits, unique within a moment | `ev1` |

### Win probability

`{home, draw, away}`, summing to 1, from the home team's side. A moment's `swing` is the
change in home win probability, so a positive swing favours the home team.

## Match events (`MatchEvent`)

One record per on-ball or match event. Types: `pass`, `carry`, `shot`, `save`, `tackle`,
`interception`, `pressure`, `foul`, `card`, `corner`, `free_kick`, `throw_in`,
`goal_kick`, `goal`, `kick_off`, `substitution`, `offside`, `period_start`, `period_end`.
Only `period_start` and `period_end` may omit `team_id`.

Outcomes are checked against the type:

| Types | Outcomes |
|---|---|
| pass and every restart (corner, free kick, throw-in, goal kick, kick-off) | `complete`, `incomplete`, `out` (kick-off: not `out`) |
| shot | `goal`, `saved`, `blocked`, `off_target`, `post` |
| save | `caught`, `parried` |
| tackle, pressure | `won`, `lost` |
| card | `yellow`, `second_yellow`, `red` |
| everything else | none |

Conventions:

- A scoring shot is a `shot` with outcome `goal`, followed by a `goal` event at the same
  `t` naming the scorer, with `assist_player_id`, `score_home` and `score_away` in its
  qualifiers.
- An incomplete pass ends where it was intercepted or went out, not where it was aimed.
- `receiver_id` is a pass's intended receiver. `related_player_id` is the other player in
  a two-player event: the player brought on (substitution), the player fouled (foul), the
  ball carrier (tackle, pressure) or the shooter (save).
- `qualifiers` holds the derived detail: `distance_m`, `difficulty` (0 to 1),
  `pressure_on_passer`, `line_breaking`, `pass_type`, `ball_speed_kmh`, `xg`,
  `shot_speed_kmh`, `body_part`, `end_height_m`, `duration_s`, `top_speed_kmh`,
  `severity`, `reason` and the goal fields above. Extra keys are allowed.

## Tracking frames (`Frame`)

```json
{"t": 57.6, "ball": [80.0, 29.0, 0.11], "players": {"ash-09": [80.0, 29.0, 8.85, 2.14]}}
```

Ten frames a second, in the pitch frame. Each player is `[x, y, vx, vy]` in metres and
metres per second. Only players on the pitch appear. Stored as JSON Lines, one frame per
line, in time order; streamed in one-second batches.

## Match metadata (`MatchMeta`)

Teams with formation, starting eleven (each with a formation slot such as `LCB` or `ST`)
and bench; stadium, referee, weather, stakes, kick-off time, simulator `seed`, and the
pre-match win probability. Player attributes are not repeated here: they live in
`league.json`.

## League and season (`League`, `Season`)

`League` is the fixed universe: clubs with names, colours, stadium, rating, default
formation, rivals and squads. Each player has a name, `short_name` for name tags, shirt,
position, role, foot, `top_speed_kmh` and nine 1 to 99 attributes (`pace`,
`acceleration`, `passing`, `vision`, `finishing`, `tackling`, `keeping`, `discipline`,
`stamina`).

`Season` is what is known before kick-off of the streamed match: the rules (points,
yellow-card ban threshold), the table with form, every fixture with its status and score,
and each player's season stats (appearances, minutes, goals, assists, shots, passes,
pass accuracy, average pass difficulty, top speed, distance, yellow cards counting toward
the next ban, reds, `last_goal_matchday`, `suspended_for`).

## Moment record (`Moment`)

The shared object the agents pass along. The detector creates it; each agent adds its
part; `status` records how far it has got: `detected`, `drafted`, `verified`,
`scheduled` or `dropped`.

| Field | Written by | Meaning |
|---|---|---|
| `type`, `t_start`, `t_peak`, `t_end`, `replay_window`, `importance` | Detector | What happened and when. `importance` above threshold slows the condensed clock |
| `involved` | Detector | Contributors, with role, events, touches, top speed and distance in the window. Player agents fan out over this list |
| `win_prob_before`, `win_prob_after`, `swing` | Stats engine | |
| `context_refs`, `evidence` | Detector and stats engine | The facts agents may use. `numbers` holds machine values for the Verifier |
| `drafts` | Lens agents | `player` keyed by player id, `club` keyed by team id, one `pundit`. A draft can be `no_box` |
| `verdicts` | Verifier | Keyed by draft key: `approved`, `repaired`, `rejected` or `fallback`, with issues and the final text |
| `director` | Director | Draft keys to show, camera shot, replay start, budget left |

Draft keys are `player:<player_id>`, `club:<team_id>` and `pundit`.

**The evidence rule.** Every number in a draft must come from an evidence item the draft
cites in `evidence_ids`. The model rejects a draft that cites an evidence id the moment
does not have; the Verifier rejects a draft whose numbers do not match the evidence.

## Overlay cues (`Cue`, `CueTrack`) and fact boxes (`FactBox`)

A cue is one timed instruction to the renderer: show this at `t_show` for `duration`
seconds of playback, on this layer, with this template.

- **Layers**: `global` (everyone sees it), `player`, `club`, `pundit`. The lens sweep swaps
  the three lens layers. Player-layer cues carry `player_id`, club-layer cues carry
  `team_id`; the browser shows the ones matching the viewer's choice.
- **Templates**: `fact_box`, `timeline_item` and `brief` carry a `box`; `speed_badge`
  carries a `badge`; `replay` carries a `camera` with a replay window; `name_tag` and
  `not_involved` are small text overlays. The browser generates `not_involved` itself when
  the selected player has no cue for a moment.
- **Camera**: one of `tv_main`, `spidercam_goal`, `corner_low`, `card_close`,
  `save_reverse`, `tactical_high`, with the replay window, replay speed (0.5 by default),
  the player to highlight, whether to draw their trail, and the speed to show on the
  speedometer.
- **Fact box**: `headline` (up to 80 characters) and `body` (one or two sentences, up to
  280) for casual viewers, plus the resolved `evidence` items and optional `analyst`
  detail (event ids, a pass map in the pitch frame, notes) for the evidence dropdown.
- **Language**: one cue per language; `lang` is a short BCP 47 tag.

A `CueTrack` is every cue for one match, sorted by `t_show`, with the list of languages it
covers.

## Changing a contract

See [ARCHITECTURE.md](ARCHITECTURE.md#changing-a-contract).
