# The Watcher, the specialists and the Explainer

`matchlens-explain` reads any match folder in the [public format](data-format.md) and produces the cards that would go on screen. Each card has an anchor ("Since 63'", "Since Ostrand red card"), one or two numbers measured against the match so far, a momentum bar showing before and now, and a cause. These parts only ever read the public tables. The generator's hidden truth is read by the scorer and nothing else.

```
matchlens-gen match --home ash --away brk --seed 7
matchlens-explain out/matches/ash-brk-7                        # print the cards
matchlens-explain out/matches/ash-brk-7 --json cards.json      # every card with all the findings behind it
matchlens-explain-eval --matches 380 --seed 9000               # score against hidden truth on unseen matches
```

## How a card is made

1. **Watcher** (`watcher.py`). It keeps the momentum scale, which is the home side's share of final-third touches, weighted toward recent minutes. It raises three kinds of moment, and never before 20':
   - **Shift:** one side's share of final-third play over the last 6 minutes is at least 25 points away from the 15 minutes before, and the last 3 minutes still lean the same way. The anchor is the minute that best splits before from after.
   - **Recovery:** a shift that only takes a team back to its own level after a dip of at least 8 points.
   - **Event:** a goal, a red card, a substitution (a team's changes within 3 minutes count as one) or half-time. It is judged once 8 minutes of play have followed, whether or not momentum moved. A shift that starts close to an event is anchored to that event.

   The Watcher works minute by minute and never looks ahead. A test checks that cards produced at minute *t* from the whole match are identical to those produced from the match cut off at *t*.

2. **Specialists** (`specialists.py`). They are independent of each other, so they can run in parallel. Each returns findings with numbers:
   - **Team play:** 21 team stats for both sides. These cover possession, pass accuracy, pass length, long balls, PPDA, defending height, high turnovers, duels won, shots, xG and running. Each compares the time since the anchor with the match so far up to the anchor, as Tristan specified. A change is measured in spreads of that stat over windows of the same length earlier in the match.
   - **Players:** the biggest individual movers on each side, each against their own match so far. Also a team-wide fatigue fade, when starters' sprints are down 20% or more and their running is also down.
   - **Substitutions:** each substitute against the player they replaced over that player's last 30 minutes. If the difference is small, it says so.
   - **Match events:** the score and game state, goals and cards around the moment, and players on the pitch.

3. **Explainer** (`explainer.py`). It settles on a cause and picks the 1 or 2 stats that show it.
   - It prefers numbers that moved in the direction of the shift and that a fan can read.
   - It shows one stat per idea, and never shows both sides of the same possession split.
   - Rates are shown as counts over the window against what was usual for that many minutes, for example "Shots: 4 in 7 min, usual 0.8". A count must differ from the usual by at least 2 to be shown.

   This is the deterministic reference. An LLM agent can take the Explainer's place and reason over the same findings, but every number still comes from the findings.

## What the stats can and can't tell you

The first version of the Explainer named the tactical change behind every spontaneous shift ("pressed higher", "went direct"). Scored against the hidden truth, those claims were right about 10% of the time, barely above chance. Here is why:

- **Most swings are not tactical.** About 70% of spontaneous shifts have no change of plan behind them at all. The rest is the ordinary ebb and flow that also drives real matches.
- **A real tweak is subtle over a few minutes.** Even when a manager did change the plan, the effect on the matching stat over the next 10 minutes was usually inside the noise. Long balls and pass length were the clearest signals, and even they were not reliable.
- **The generator is not the reason.** We checked it against the real season in two ways:
  - Team styles spread as widely as real ones. Across the 20 teams, the spread of defending height, PPDA, long-ball share and pass length is at least as wide as in 2017-18.
  - Red cards reshape the 10-man team as often as in reality. In the 15 minutes after a red card, generated 10-man teams defend lower in 71% of cases (real: 73%), make fewer passes in 94% (real: 86%) and have less final-third play in 82% (real: 86%).
- **Territory drags other stats with it.** When a team pins the other back, its defending height, crosses and high turnovers rise with the territory, not because anyone asked. `calibrate.py` learns from unlabelled matches how much each stat moves with field tilt alone, so that only the remainder counts as a change of style.

So the Explainer now claims only what stats can support:

| Cause | When |
|---|---|
| `red_card_reshape` / `red_card_holding` | The 10-man team's passes, possession or defending height clearly dropped, or didn't. |
| `chasing_the_game` / `goal_lift` / `goal_no_reaction` | Which side gained after a goal. |
| `substitution_impact` | The substitute's numbers clearly differ from the replaced player's. |
| `fatigue` | A team-wide fade on the side that lost momentum. |
| `play_change` / `recovery` | Everything else. The card shows *what* changed in play (duels won, possession, shots) without claiming an instruction nobody can see. This is the honest answer for most spontaneous shifts, and it matches the real-season finding that the "why" is usually in how play changed rather than in one event. |

## How well it does

Scored on 380 unseen generated matches (season seed 9000; tuning used seed 2026):

| Check | Result |
|---|---|
| Shifts where the hidden state really moved toward the side that gained | 81% (random windows: 69%) |
| Event-mode shifts where the event really led to a change of plan | 86% |
| Fatigue claims backed by a real fade | 88% (240 claims) |
| "Chasing the game" claims where the trailing team's plan really moved | 63% (244) |
| Red-card claims | 13 reshape claims, 54% right; 19 holding claims, 32% right. Too few to tune yet. |
| All checked cause claims | 73% (516) |

CI runs the same scoring on 100 unseen matches and fails if shifts stop beating random windows by at least 5 points, if event backing falls below 75%, or if checked claims fall below 65%.

## Next

- Run the specialists as agents (Foundry, with the shared findings record in `design.md`). The Explainer becomes an LLM agent that reasons over findings, and a Verifier rechecks every number from the events.
- A Director that limits cards per spell. The pipeline raises about 12 candidates per match, and each carries `salience` and `show`.
- The broadcast graphics.
