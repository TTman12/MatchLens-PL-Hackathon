# Match data format (v1.0)

MatchLens reads any match supplied in this format. The format doesn't care whether the match came from our generator or from somewhere else.

A match is one folder:

| File | Required | What it holds |
|---|---|---|
| `match.json` | yes | Teams, players (with role and starter flag), venue and final score |
| `events.jsonl` | yes | One event per line, in time order |
| `physical.csv` | no | Distance, high-speed running and sprints per player per minute |
| `team_minute.csv` | derived | Per-team stats for each minute, built from the events (and from `physical.csv` when present) |
| `player_minute.csv` | derived | Per-player stats for each minute, for players on the pitch |

You can rebuild the derived tables for any folder with `matchlens.data.aggregate.aggregate(meta, events, physical)`.

The generator writes its hidden ground truth (the coaching decisions behind a match) to `out/truth/<match_id>.json`, outside the match folder. Nothing that reads a match can see it.

## Coordinates and time

- **Pitch:** coordinates are in metres on a 105 × 68 pitch, in the **acting team's attacking frame**. The team's own goal line is at x = 0 and it attacks toward x = 105. y runs from 0 (left) to 68.
- **`period` and `t`:** `period` is 1 or 2. `t` is seconds since the start of that period.
- **`m`:** the continuous match minute, counting first-half stoppage time before the second half starts. All per-minute tables are keyed by `m`.
- **`clock`:** the broadcast clock, e.g. `45+2:14`.

## Events

Every event has `id`, `period`, `t`, `m`, `clock`, `team_id`, `player_id` (null for ball-out and whistle events), `type`, `subtype`, `x`, `y`, `end_x`, `end_y`, `outcome` and `possession`. Optional fields are listed against each type below.

| type | subtypes | outcome | optional fields |
|---|---|---|---|
| `pass` | `short`, `high`, `header`, `cross`, `long`, `through`, `throw` (open play); `free_kick`, `free_kick_cross`, `corner`, `throw_in`, `goal_kick` (restarts) | `complete` / `incomplete` | `receiver_id`, `kick_off` |
| `duel` | `ground`, `loose_ball`, `aerial` | `won` / `lost` / `neutral` | `duel_id` and `opponent_id` (each duel is written once per team, sharing a `duel_id`); `duel_role` (`attacking`/`defending`) on ground duels |
| `carry`, `touch`, `clearance` | as type | | |
| `shot` | `open_play`, `free_kick`, `penalty` | `goal` / `saved` / `off` / `blocked` / `post` | `xg`, `header` |
| `foul` | `foul` | `foul` | `card` (`yellow`, `second_yellow`, `red`) |
| `save`, `keeper_sweep`, `offside`, `ball_out` | as type | | |
| `stoppage` | `whistle` | | `marker` (`period_start`, `period_end`) |
| `substitution` | `substitution` | | `player_off_id` (the player coming on is `player_id`) |

## Per-minute tables

**`team_minute.csv`** has one row per team per minute, made up of:

- **Context:** `m`, `period`, `clock_minute`, `team_id`, the score at the start of the minute (`goals_for_before`, `goals_against_before`) and `players_on`.
- **Passing:** passes, completed passes, passes in their own half, passes in their own 60% (`passes_build_up`, for the opponent's PPDA), the summed length of passes (`pass_length_sum`), passes in the final third (attempted and completed), progressive passes, long passes and crosses.
- **Territory:** final-third and box entries, touches, and touches in the final third.
- **Duels:** duels and duels won, and aerial duels and aerial duels won.
- **Defending:** defensive actions, plus the sum of their x positions. Divide it by the count to get the average defending height. `defensive_actions_high` counts those in the opponent's 60%; PPDA is the opponent's `passes_build_up` divided by it.
- **Pressing:** `high_regains`, which counts balls won within 40 m of the opponent's goal.
- **Attacking:** shots, shots on target, xG and goals.
- **Discipline and set pieces:** fouls, yellow and red cards, corners and offsides.
- **Physical:** distance, high-speed running and sprints, summed over the team.

**`player_minute.csv`** has one row per player per minute on the pitch. The columns are touches, passes, completed passes, progressive passes, duels, duels won, defensive actions (with their x sum), shots, xG, goals, fouls, distance, high-speed running and sprints.

## Physical data

Event data has no physical numbers. In generated matches they are **modelled**, not measured, from typical published elite ranges by position. They respond to the team's plan, ball-in-play time and the player's fatigue. `match.json` says so in `physical_note`. A real data source would put measured values in the same columns.
