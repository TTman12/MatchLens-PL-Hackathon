# Taking a match live from another provider

MatchLens doesn't need our generator or our raw event stream. A match can arrive live from any provider as **per-minute tables**: one row per club and one row per player on the pitch each minute, plus the minute's key events. The provider uses its own column names, and a small mapping file says which of its columns is which of ours.

The code is in `matchlens/ingest/`:

| Part | File | What it does |
|---|---|---|
| Feed adapter | `feed.py` | Renames the provider's columns, works out the score, players on the pitch and half-time from the events, and builds the match up one minute at a time |
| Column mapping | `mappings/example-provider.json` | Provider column name on the left, ours on the right |
| Live runner | `runner.py` | Each minute: add it, check for a shift, send new moments to the explainer, let the Director decide |
| Unseen-match test | `unseen.py` | Fresh matches sent as a provider's feed, checked end to end |

```
matchlens-feed export out/matches/ash-brk-7 feed/ash-brk-7      # write one of our matches as a provider's feed
matchlens-feed run feed/ash-brk-7                               # play it through a minute at a time
matchlens-feed run feed/ash-brk-7 --agents foundry --pace 2     # the agent crew on Microsoft Foundry, a minute every 2 s
matchlens-feed run feed/ash-brk-7 --mapping their-names.json    # another provider's column names
matchlens-feed unseen                                           # the unseen-match test
```

## The feed

A feed folder holds four files. A live connection sends the same rows a minute at a time (`feed.to_minute` turns one minute of rows into what the runner takes).

| File | Rows | Example provider's columns |
|---|---|---|
| `lineups.json` | Clubs and players: id, name, role, starter. No result. | `Player`, `FullName`, `Known`, `Pos`, `Starting` |
| `club_minutes.csv` | One per club per minute | `Tick`, `Half`, `MatchClock`, `Club`, `Passes`, `FinalThirdTouches`, `ExpectedGoals`, ... |
| `player_minutes.csv` | One per player on the pitch per minute | `Tick`, `Club`, `Player`, `Touches`, `Duels`, `DistanceMetres`, ... |
| `events.csv` | Kick-offs, goals, cards and substitutions | `Tick`, `EventId`, `Half`, `Clock`, `Kind`, `Club`, `Player`, `PlayerOff` |

`Tick` is the minute's place in the match (0, 1, 2, ...), counting stoppage time, so minutes arrive in order with none missing. The stats are the ones in [data-format.md](data-format.md). The score before each minute, the players on the pitch and half-time are worked out from the events, so a provider needn't send them. If it does send them under a mapped name, its values are used.

The mapping file has one section per file (`team`, `player`, `events`, `lineup`) plus `kinds` for the event names. Columns it doesn't name are ignored. If a provider never sends one of our columns, the run says so at the end (`LiveMatch.missing`), because any number built on it would read as zero.

## What runs each minute

1. The adapter adds the minute. Its view of the match is exactly what has arrived: nothing later exists yet.
2. The Watcher checks whether something now needs explaining (`Watcher.step`). It decides on the spot and never revises a moment it has already raised. For example, once a goal has had its own look after 8 minutes, a later shift can't take it over.
3. Each new moment goes to the explainer: the deterministic rules, or the agent crew (four specialists, the Explainer and the Verifier) offline or on Foundry.
4. The Director decides at once whether the card goes on screen (`Director.offer`). It doesn't hold a card back in case a better one turns up.
5. When the crew runs, the cards that go up get their lines from the Interpreter and the Analyst.

The one-go path that makes the demo bundles (`watch` and `direct`) is these same live steps run over a whole match. That is why a recorded match and a live feed give the same cards.

Making the Watcher and Director strictly live changed little. Over 100 evaluation matches (seed 9000), shifts matching a hidden swing went from 82.7% to 83.0% and checked claims from 74.8% to 76.5%. Over 60 matches, the on-the-spot Director put up 85% of the same cards as the old one, which could see up to 5 minutes ahead. Average salience was 1.30, against 1.35 before.

## The unseen-match test

`matchlens-feed unseen` generates fresh matches with new seeds and pairings that nothing was tuned on. It sends each one only as a provider's feed: renamed per-minute tables and key events, with no final score, seed or raw event stream, and with the hidden truth held back. It plays the feed through the adapter and the live runner, explains the original match folder in one go, and passes only if:

- **tables:** the adapter rebuilt exactly the tables the original match has;
- **numbers:** every number on every card going on screen, recomputed from the original match's events, is the same, and so is the momentum bar;
- **no look-ahead:** the live run raised the same moments, made the same cards and put the same ones on screen as the one-go run, though it never had a minute it hadn't reached; and
- **causes:** scored against the hidden truth, the live cards clear the same floors as `matchlens-explain-eval --check`. This is judged from 20 matches up.

Result on 30 unseen matches (seed 5150, about 30 s):

| Check | Result |
|---|---|
| Tables rebuilt exactly | 30 of 30 |
| Numbers on screen that recompute | 345 of 345, on 192 cards |
| Live = one-go (moments, all 338 candidates, cards on screen) | 30 of 30 |
| Shifts matching a hidden swing | 82.4% (random windows 65.2%) |
| Event shifts backed by truth | 82.3% |
| Checked cause claims correct | 71% of 31 |

CI runs the 30-match test on every pull request (the `unseen` job), and `pytest` runs a 3-match version.

With `--agents foundry`, the first match also goes through the agent crew on Foundry, live. The models choose, so the cards can differ from the rules. What must still hold is that every number recomputes, the moments are the same, and the live Director's choices match a one-go Director over the same cards. The report also lists the crew's causes, fallbacks and claims scored against the truth. This needs `pip install -e ".[foundry]"` and `AZURE_AI_PROJECT_ENDPOINT`, and costs about 65 model calls.

## What a real feed would still need

- **Calibration:** `matchlens/explain/calibration.json` was fitted on generated matches. A real feed's numbers should be refitted with `calibrate.py` before trusting the effect sizes.
- **No truth:** a real feed has no hidden truth, so the causes can't be scored. The numbers and the no-look-ahead checks still apply.
- **Physical columns:** distance, high-speed running and sprints come from tracking. A provider without tracking leaves them out, and cards built on them won't appear (the run lists them as missing).
