# What real matches say about momentum shifts

Measured on 20 Oct 2026 from the Wyscout public event data for the full 2017-18 Premier League season. That is 380 matches and 643,150 events, released under CC BY 4.0 by Pappalardo et al. (2019, *Scientific Data* 6:236), via figshare collection 4415000. The data was used only to measure patterns. None of it is shipped, and no real names are used.

Scripts are in `research/`: `prep.py` builds the per team-minute and per player-minute aggregates, and `analyse.py`, `null.py` and `drivers.py` run the analyses. Run them with `python3 -I scripts/prep.py <wyscout_dir> agg.pkl` and then `python3 -I scripts/analyse.py agg.pkl`. Download links: events `https://ndownloader.figshare.com/files/14464685`, matches `https://ndownloader.figshare.com/files/14464622`.

**Sanity check.** The data averages 432 passes per team per match at 82.5% accuracy. It has 999 goals (the official total is 1,018; own-goal tagging accounts for most of the gap), 41 red cards, and every substitution with its minute.

## Definitions

- **Field tilt:** a team's share of both teams' events in the final third. Wyscout's x coordinate runs from 0 to 100 from the acting team's own goal.
- **Momentum shift:** field tilt in the last 5 minutes differs from the 10 minutes before by at least 30 percentage points. At least 8 final-third events are required in each window, and shifts must be at least 10 minutes apart.
- **Effect sizes:** "Δ" means the share after the event minus the share before it. A control is the same measurement on random windows with no event in them.

## Findings

### 1. Shifts are real, frequent, and mostly not noise
- There are **5.6 shifts per match**.
- To test for noise, I kept each match's real event counts but randomly reassigned final-third events between the two teams at the match's average rate. That produces only **0.8 shifts per match**, so about 85% of detected shifts are genuine changes in play.
- There are 22 final-third events per 5 minutes (both teams together), so a 5-minute window is just enough to measure, and 2 minutes is too few.

### 2. Most shifts have no discrete trigger
For each shift, I checked whether a goal, substitution, half-time or red card happened in the previous 15 minutes, and compared that with random windows:

| Trigger in the previous 15 min | Share of shifts | Share of random windows |
|---|---|---|
| Goal by the team that lost momentum | 21.4% | 18.1% |
| Goal by the team that gained it | 16.5% | 18.4% |
| Sub by the gainer | 31.9% | 30.8% |
| Sub by the loser | 28.8% | 31.6% |
| Half-time | 17.8% | 18.9% |
| Red card (either side) | 1.5% | 1.9% |
| **None of these** | **30.8%** | |

- Only "the team that lost momentum had just scored" is somewhat enriched; the team that concedes then pushes.
- Subs and half-time occur at their background rates.
- **Implication:** the honest answer to "why did momentum shift?" is usually found in *how the play changed*, not in a single event. The play-stats specialists are the core of the system. The substitution and half-time specialists will often, correctly, find nothing.

### 3. What the play looks like during a shift
These are changes in the last 5 minutes versus the 10 before, at shifts compared with random windows. Each is given in units of that metric's random-window spread (SD).

| Feature | Mean Δ at shifts | Effect |
|---|---|---|
| Gainer's pass share | +18 pts | +0.92 SD |
| Loser's share of passes made in their own half | +21 pts | +0.82 SD |
| Height of the gainer's defensive duels | +15 m up the pitch | +0.75 SD |
| Height of the loser's defensive duels | −13 m (pushed back) | −0.73 SD |
| Gainer's metres progressed per minute | +9 m/min | +0.46 SD |
| Gainer's share of duels won | +10 pts | +0.45 SD |
| Loser's pass accuracy | −8 pts | −0.40 SD |
| Gainer's pass accuracy | +4 pts | +0.38 SD |
| Loser's fouls per minute | small | +0.14 SD |

- **Caveat:** these features move *with* the shift, so they partly describe it rather than cause it. Finding a cause needs a lead-lag test (what changed in the 5 to 10 minutes *before* the territory swung, such as the gainer's pressing height or duel wins). That analysis is the next step.
- **This is the graphic vocabulary.** "Their defending line is 15 m higher", "we're winning 10% fewer duels" and "our passing accuracy is down 8 points" are exactly the numbers Tristan described, and real shifts produce them at these sizes.

### 4. Discrete-event effects, where they do exist
- **Conceding a goal:** in the 10 minutes after, the conceding team's field tilt rises by a median of **+9.7 pts** and its pass share by **+6.3 pts** (n=411 isolated goals). This is the score effect.
- **Red card:** the 10-man team's pass share falls by a median of **−19 pts** over the next 15 minutes (n=22). Large, but rare (about 1 in 9 matches).
- **Substitution, at team level:** this effect is small.
  - When losing, the subbing team's field tilt rises by **+6.5 pts** against a control of +2.3, a net of about +4 pts.
  - When drawing, the net is about +2 pts.
  - When winning, the net is about +1 pt.
  - The spread is wide, so individual subs can matter a lot even though the average effect is small.
- **Substitution, at player level:** this effect is clear. In their first 15 minutes, a substitute makes **+22% more duels per minute**, +12% more on-ball events and +7% more passes than the player they replaced did in his last 15 minutes. This "fresh legs" effect is real and measurable.
- **Half-time:** there is no average shift for any score state. However, **31 to 44% of teams change field tilt by 20 points or more** between the end of the first half and the start of the second, in both directions. Half-time changes happen, but the score doesn't predict which way.
- **Late game:** from minute 75, winning teams average 47.6% of passes and 45.5% field tilt, and losing teams 52.4% and 54.5%.
- **Per-player activity over a match (players who played the full 90):** on-ball events per minute by 15-minute block are 0.81, 0.76, 0.83, 0.75, 0.69, and 0.87 (the last block includes stoppage time). The dip from 60 to 75 minutes is the only fatigue signal visible in event data.

## What this means for the build

1. **Generator.** Plant causes at real effect sizes:
   - subs as player-level duel and activity boosts of about +20%, with a team effect of a few points unless the sub changes the plan;
   - half-time plan changes at ±20 pts in about a third of matches;
   - a conceding team that pushes by about 10 pts;
   - reds at −19 pts;
   - and, above all, *play-driven* shifts with no discrete trigger, such as a press that starts working, an opponent who starts going long, or a duel battle that turns.

   Aim for about 5 or 6 shifts per match, with about 30% having no event trigger.
2. **Agents.** The system must be allowed to say "no substitution or half-time cause; the shift came from X in play", and the evaluation should score that too.
3. **Realism check.** Every table above becomes a test: generated matches must reproduce these numbers within their spread.
4. **Physical data** (distance, sprints) isn't in this dataset. Model it from sports-science ranges and label it as modelled.

## 5. Do big events actually cause shifts? (added after Tristan's 11:14 steer)

Script: `research/followthrough.py agg.pkl <size>`. A "sustained shift" is when a team's field tilt over the 10 minutes after the event differs from the 10 minutes before by at least the given size. The baseline uses random minutes.

| After... | ≥20-pt sustained shift | ≥30-pt sustained shift |
|---|---|---|
| A random minute (baseline) | 41% | 21% |
| Conceding a goal | 44% | 24% |
| A red card (10-man team, n=24) | 46% | 29% |
| A substitution | 43% | 22% |
| A double or triple sub | 43% | 26% |
| Half-time | 40% | 18% |

**Big events barely raise the chance of a big shift above background.** Tristan's point holds: most events do not cause a momentum change.

**But events do change how a team plays.** In the 15 minutes after a red card, compared with the 15 before, the 10-man team:
- defends lower in 73% of cases (median −7.7 on the 0 to 100 pitch scale);
- makes fewer passes per minute in 86% of cases;
- has fewer final-third events in 86% of cases.

So the chain is: **event → change of plan or style (common) → visible momentum shift (sometimes)**. Whether a shift happens depends on how the opponent responds and on chance.

**Generator rule.** Momentum is never written directly. Each event has a *probability* of triggering a plan change, and the plan change alters behaviour parameters such as pressing height, directness, risk and duel intensity. Plan changes can also happen with no trigger at all, for example a press that tires or a tweak at 30 minutes. Play stats and momentum then emerge from the simulation. The ground-truth log records each link in the chain (event, decision, parameter change), so evaluation can check both:
- that the agents connect a shift to the right chain;
- that they do **not** blame an event that didn't cause one.

The case "they changed plan and it held, with no shift" is a story in its own right.

## 6. What changes before a swing? (lead-lag test)

Script: `research/leadlag.py`. A swing is measured as field tilt over [t, t+5) against [t−10, t). The "lead" is the change from [t−20, t−10) to [t−10, t−5), so it is measured before the swing starts. Effects are in units of the random-window spread (SD).

- **Before a swing, the team that goes on to gain is usually dipping.** Its field tilt falls by 16.5 pts beforehand (−0.59 SD against random windows). Its pass share, defending height, duel share and progression all fall too (−0.2 to −0.4 SD).
- **So many detected "shifts" are recoveries.** Momentum oscillates, and a short before/after comparison flags the bounce-back from a dip as a new shift.
- **No event-data stat gives early warning of a genuine new shift.** None of these stats moves in the gainer's favour before the swing.

**Implications:**
1. **The detector needs a longer baseline.** It should compare against the team's level over the match so far, and against its expected level from pre-match strength and game state, not only against the previous 10 minutes. It should then label each swing as a new shift or a recovery to normal. Recovery is a legitimate graphic of its own ("back to their level after a 10-minute wobble").
2. **Mode 2 causes are read from the stat signature *during* the change, not from early warnings.** For example, a fatigue fade shows as declining duels per minute and dropping defending height over 15 to 20 minutes. An instruction shows as an abrupt step in directness, defending height or pass share.
3. **The generator must reproduce this oscillation.** Real matches wobble around a level. A generator that holds a flat level until a planted cause will fail the realism tests.
