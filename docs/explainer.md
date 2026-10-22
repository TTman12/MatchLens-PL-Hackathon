# The Watcher, the specialists and the Explainer

`matchlens-explain` reads any match folder in the [public format](data-format.md) and produces the cards that would go on screen. Each card has an anchor ("Last 6 minutes", "Since B. Ostrand red card"), one or two numbers measured against the match so far, a momentum bar showing before and now, and a cause. These parts only ever read the public tables. The generator's hidden truth is read by the scorer and nothing else.

```
matchlens-gen match --home ash --away brk --seed 7
matchlens-explain out/matches/ash-brk-7                        # print the cards
matchlens-explain out/matches/ash-brk-7 --json cards.json      # every card with all the findings behind it
matchlens-explain-eval --matches 380 --seed 9000               # score against hidden truth on unseen matches
```

## How a card is made

1. **Watcher** (`watcher.py`). It keeps the momentum scale, which is the home side's share of final-third touches, weighted toward recent minutes. It raises three kinds of moment, and never before 15':
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
   - When the shift is about how play changed, it looks for a **play-style story** first: two stats that moved together for one team and together mean something (`stories.py`). Possession up *and* more passes in their own half means a team is keeping the ball and playing it safe, so the other side can't attack. Defending deeper *and* more clearances means a team is sitting deep, which is why the other side has the ball but can't score. There are 13 stories; each needs both stats to move at least 1 spread, one of them at least 1.5.
   - A share (possession, field tilt) never goes on a card alone: on its own it says nothing about why. If no story fits, it gets the partner stat that moved most with it.
   - It shows one stat per idea, and never shows both sides of the same possession split.
   - When no story fits, one or two players on the side that gained who are clearly doing more can carry the card instead: at least 3.5 spreads up on tackles (defensive actions), duels won, forward passes, sprints or distance. The card names them: "Wexez is making more tackles, and Pennholt is covering more ground."
   - Every card carries one line saying what is going on, written three ways: for a neutral and for fans of each team (`text`). It is an inference, not a read-out (`insight.py`): the stats point to a reading of the game (a side has gone on the attack, is pressing, is under pressure, is running the game, has gone direct, has a player driving it on), and the score sets the angle. A side a goal down that has pushed up "has gone on the attack, looking for a way back into the game"; its own fans read that it "is piling forward and looks the likelier side to score next"; the other side's fans read that their team is "having to defend as Brackenford throw everything forward". With the agents, the Interpreter writes these lines from the same facts ([agents.md](agents.md)).
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

Scored on 380 unseen generated matches (season seed 9000; tuning used seed 2026; re-run on 22 Oct 2026 after moments were allowed from 15'):

| Check | Result |
|---|---|
| Shifts where the hidden state really moved toward the side that gained | 82% (random windows: 69%) |
| Event-mode shifts where the event really led to a change of plan | 85% |
| Fatigue claims backed by a real fade | 89% (262 claims) |
| "Chasing the game" claims where the trailing team's plan really moved | 60% (239) |
| Red-card claims | 11 reshape claims, 55% right; 21 holding claims, 33% right. Too few to tune yet. |
| All checked cause claims | 73% (533) |

CI runs the same scoring on 100 unseen matches and fails if shifts stop beating random windows by at least 5 points, if event backing falls below 75%, or if checked claims fall below 65%.

## What came next

All built since this part was written:
- The specialists and the Explainer run as agents on Microsoft Foundry, with a shared findings board and a Verifier that rechecks every number ([agents.md](agents.md)).
- A Director keeps about 5 or 6 of the 12 candidate cards a match ([broadcast.md](broadcast.md)).
- The broadcast screen, with fan and admin screens ([broadcast.md](broadcast.md)).
