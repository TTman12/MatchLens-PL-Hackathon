# The synthetic match generator

`swing-gen` writes fictional matches that behave like real Premier League matches. Each match has a full event stream, minute-by-minute team and player tables, and modelled physical output. It also writes a hidden record of *why* each match went the way it did. The fictional clubs and squads are in `data/league.json`.

```
pip install -e .
swing-gen clubs
swing-gen match --home ash --away brk --seed 7     # -> out/matches/ash-brk-7/ and out/truth/ash-brk-7.json
swing-gen season --limit 40
swing-realism                                       # generate 380 matches and check them against the real season
```

## How it works

1. **Learned from a real season, then generated fresh.**
   - `research/learn_priors.py` reads the public Wyscout event data for the 2017-18 Premier League (Pappalardo et al. 2019, CC BY 4.0).
   - It writes only aggregate tables to `swing/gen/priors.json.gz`:
     - which action follows which, by pitch zone;
     - how far passes travel and how often they succeed;
     - timing between actions;
     - which positions make which actions;
     - an xG model, card rates and substitution timing.
   - No real match, team or player is stored or shipped.
2. **The engine** (`engine.py`) plays a match action by action, sampling from those tables. Each choice is reweighted by:
   - both teams' current **plans** (block height, pressing, directness, tempo, width, risk, aggression, shooting, time-wasting);
   - player quality, home advantage and **fatigue**;
   - **numbers on the pitch**;
   - a slowly drifting **flow** term. This is the ordinary ebb and flow of a match, and it is what makes real matches wobble.
3. **The coaching layer** (`manager.py`) decides when plans change:
   - **After events, only sometimes:**
     - a red card leads to parking the bus 73% of the time;
     - a conceding team may push;
     - a winning team may protect its lead;
     - substitutes may come with new instructions.
   - **At half-time:** a new plan in some matches.
   - **Spontaneously:** an instruction from the touchline at any point.
   - **Continuously:**
     - teams react to the score (trailing teams push and take risks; leading teams sit deeper);
     - players tire;
     - opponents sometimes respond to a change.
4. **Physical output** (`physical.py`) is modelled per player per minute from position, plan, ball-in-play time and freshness.

**Momentum is never written directly.** Possession, territory and momentum come out of the actions. An event can change a plan, and a plan change can still fail to move momentum, just as in real matches.

## The hidden truth

`out/truth/<match_id>.json` holds two things, and only the evaluation reads it:

- **`decisions`:** every change of plan, with its minute, team, kind, what triggered it (an event id, `half_time`, `game_state`, `response`, or `none`) and the parameter change. It also records each substitution and the minute each team's fatigue started to bite.
- **`minutes`:** each team's plan, flow, freshness and players on the pitch, minute by minute.

## Realism gate

`swing-realism` generates a full 380-match season and measures it with the same code used on the real season (`swing/realism/`). It then checks 31 numbers against tolerances, and CI runs it on every push. They cover:

- volumes: passes, accuracy, duels, shots, fouls, goals, cards and subs;
- how matches split: home pass-share spread, home wins and draws;
- momentum behaviour:
  - shifts per match against the noise floor;
  - the share of shifts with no trigger;
  - whether subs or half-time precede shifts more often than chance;
  - how often events lead to a sustained shift;
  - the pre-swing dip;
- event effects: conceding, red cards, substitutes' extra duels, half-time swings, late score effects and fatigue.

The latest report is in [realism.md](realism.md). The tuning constants are at the top of `engine.py` and `manager.py`.
