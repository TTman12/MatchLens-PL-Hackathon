# The match simulator

`matchlens/sim` plays complete synthetic football matches in a fictional 20-club league
and writes them in the shared formats ([contracts.md](contracts.md)): events, 10 Hz
tracking frames, match metadata with a pre-match win probability, and, for a whole
season, the table, fixtures and player season stats. Everything is seeded: the same
seed gives the same match, frame for frame.

## Run it

```bash
pip install -e ".[dev]"

# One match, every file, validated against the contracts as it is written (about 7 s)
matchlens-sim match --home ash --away brk --seed 1325 --out out/match

# The same with a scripted storyline (comeback, red_card, late_winner, or a JSON file)
matchlens-sim match --storyline comeback --out out/comeback

# The season before the featured match: 290 matches on the same engine
matchlens-sim season --out data/season --matchday 30 --workers 4

# The featured fixture of that season, with its suspensions and stakes
matchlens-sim featured --season-dir data/season --storyline comeback --out out/featured

# Calibration against real-world ranges, and seed scouting for demos
matchlens-sim calibrate --matches 380 --report docs/calibration.md
matchlens-sim scout --home ash --away brk --seeds 200
```

`match` and `featured` write `match.json`, `events.json`, `frames.jsonl` (about 60,000
frames, 45 MB; `--no-frames` skips them) and `league.json`; `featured` also copies
`season.json`, so the folder has the same files as [data/sample](../data/sample).

From Python:

```python
from matchlens.sim.league import build_league
from matchlens.sim.match import simulate_match

match = simulate_match(build_league(), "ash", "brk", match_id="m291", seed=1325)
match.meta  # MatchMeta
match.events  # list[MatchEvent]
for frame in match.iter_frames():  # Frame dicts, rendered lazily at 10 Hz
    ...
```

## How a match is played

The engine ([engine.py](../matchlens/sim/engine.py)) is event-driven, with movement
recorded between events.

- **Team shape.** Each club plays its formation (4-3-3, 4-2-3-1, 3-5-2 or 4-4-2). Every
  player has a slot that shifts with the ball: up and wide in possession, compact and
  goal-side out of it, with the back line never sinking onto its own goal line and
  attackers held onside of the last defender
  ([formations.py](../matchlens/sim/formations.py)). The nearest defender presses the ball
  and the next one covers.
- **Decisions.** Whenever a player has the ball they score every option from the current
  positions of all 22 players: a pass to each team-mate, a through ball into space, a
  cross, a carry in five directions, a shot, or a clearance. Each option's value is its
  success probability times the threat of where the ball ends up, minus the risk of
  losing it there. A seeded softmax picks one; better vision means sharper choices.
- **Outcomes** come from small closed-form models ([models.py](../matchlens/sim/models.py)):
  pass success from distance, how open the lane is, pressure on the passer and receiver,
  and the passer's rating (the same factors without the rating give the pass difficulty);
  carries succeed less for every defender in the way; xG from distance, goal-mouth
  angle, pressure, headers and how many defenders stand between shooter and goal; goals
  against keeper rating. A failed pass is intercepted in the lane, overhit out of play,
  or lost at the receiver, which gives throw-ins, goal kicks and corners.
- **Duels and discipline.** Defenders close down receivers (pressure events) and
  sometimes tackle. Fouls come from mistimed tackles and holding; a card depends on the
  foul's severity and the player's discipline, and a booked player is more careful.
- **Dead time is real.** Restarts take setup time, goals take a celebration at the corner
  flag and a walk back for the kick-off, and substitutions (two or three windows after 55
  minutes) and cards stop the clock. Added time follows the stoppages. Replays live in
  this dead time.
- **Fatigue and home advantage.** Top speed drops with minutes played, less for players
  with high stamina. The home side passes and finishes slightly better.

Movement is speed-limited per player. Between events each player heads for their slot
(or, when part of the action, a pin they can reach: the receiver running onto a pass, the
tackler arriving at the ball). [render.py](../matchlens/sim/render.py) then draws each
player along a smooth curve through those keyframes, so velocities in the frames are
continuous and stay under each player's top speed, and the ball follows passes, shots,
carries and restarts without jumping.

Time is kept in ticks of 0.1 s, so every event lands exactly on a frame.

## Scripted storylines

A storyline is a list of beats: a goal or a card, for a side, at a minute, optionally for
a shirt number ([storyline.py](../matchlens/sim/storyline.py)). Once a beat is due the
engine tilts play toward it (the scripted side wins the ball back and its attacks run at
goal; for a card, the booked side is defending when the challenge comes) and it usually
lands within a few minutes. The build-up is still simulated, so it looks like football.
In `strict` mode every other goal and dismissal is turned into a near miss, so the
scoreline is exactly the script's. Players a later beat needs are not substituted.

| Name | What happens |
|---|---|
| `comeback` | Away side 2-0 up by half-time, then down to ten men; home side win 3-2 with a winner from their number 9 in added time |
| `red_card` | A first-half straight red for the away side; the rest plays out naturally |
| `late_winner` | 1-1, then the home number 9 wins it after 88 minutes |

A JSON file works too:

```json
{"name": "my_story", "strict": true,
 "beats": [{"minute": 12, "kind": "goal", "side": "home", "shirt": 9},
           {"minute": 70, "kind": "red", "side": "home"}]}
```

## The season

[season.py](../matchlens/sim/season.py) builds a double round robin for the 20 clubs
(circle method, home and away balanced), moves the featured fixture to the featured
matchday, and plays every earlier matchday headless on the same engine. Each match's seed
is derived from the season seed and its match id, so any single match can be replayed
on its own. It adds up:

- the table and last-five form;
- every fixture, with scores for those played;
- each player's appearances, minutes, goals, assists, shots, passes, pass accuracy,
  average pass difficulty, top speed and distance (from the movement, not invented);
- discipline: five yellows trigger a one-match ban and the count resets; a second yellow
  bans for one match, a straight red for three. Bans are served in the following
  fixtures, and `suspended_for` lists the upcoming match ids a player will miss,
  including the featured one.

`featured_context` turns the table into plain-fact stakes notes for `match.json` ("A win
would take Ashmere top", "Halloway is one booking from a ban") and a form-adjusted
pre-match win probability.

## Pre-match win probability

Two independent Poisson goal counts whose means come from the clubs' ratings, with a
home advantage ([models.py](../matchlens/sim/models.py)). For the featured match the
ratings are nudged by points per game so far. It is a synthetic estimate of who is
likely to win, not betting odds.

## Realism checks

`tests/test_sim.py` runs on every push:

- the same seed gives identical metadata, events and frames; a different seed differs;
- written files validate against the Pydantic contracts and the JSON Schemas;
- events are in time order with sequential ids, every goal follows its scoring shot, the
  final goal's score matches the result, and only players on the pitch act;
- frames are continuous at 10 Hz, no player exceeds their top speed or jumps between
  frames, the ball never travels faster than a hard shot, and full-match outfield
  players cover a realistic 8 to 13 km;
- over 24 matches, per-match averages of goals, shots, shots on target, xG per shot,
  passes, pass completion, corners, fouls, cards, offsides, throw-ins, ball in play and
  match length fall in football-like ranges;
- each storyline produces its script (score, order, timing, scorer);
- the schedule is a valid double round robin; a short season's table, goals and player
  stats add up; bans follow the rules.

The full calibration over a season's worth of matches is in
[calibration.md](calibration.md).

## Limits

- Events come from the simulator, not from video. The engine is where a vision model
  would plug in for auto-eventing; we did not build that.
- Player movement is a shape model with pressing, not full off-ball intelligence: runs
  in behind and overlaps appear through the shape and through balls, not as planned
  patterns.
- At half-time the frames cut from one end to the other (the break is not on the
  timeline), so don't difference positions across the first frame of period 2.
- Positions can sit a little outside the touchline when a player takes a throw-in.
