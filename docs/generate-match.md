# Generate match: an unseen match, live on the site

The live site plays six prebuilt demo matches. **Generate match** (or the G key) makes a brand-new
one and plays it through the whole pipeline while you watch, so the unseen-match path
([live-feed.md](live-feed.md)) can be seen working rather than taken on trust.

```
press Generate match ──► POST /api/generate
                          │  random seed (100000-999999) and a random pairing of the 20 fictional clubs
                          ▼
                     generator ──► match folder + hidden truth
                          │  written as a provider's feed: per-minute club and player tables and
                          │  key events, no final score, no seed. The folder and truth are deleted.
                          ▼
                     LiveRunner, one minute at a time (a minute every 0.5 s)
                          │  Watcher.step → crew (4 specialists + Explainer + Verifier) → Director
                          │  → Interpreter and Analyst on the cards going up
                          ▼
                     the screen's bundle, rebuilt from the minutes so far ──► GET /api/live/<id>
                                                                                │  polled every 1.5 s
                                                                                ▼
                                                                         web/live.js → app.js
```

The screen's clock never passes the last minute the feed has sent; the striped part of the timeline
is what hasn't arrived yet. If the clock catches up (4x speed, or a slow moment on Foundry), the
badge says the agents are working on that minute and the clock waits. The badge on the feed shows
the seed and that no truth data was used. At full time the Recapper writes the recap headlines and
the Translator the Spanish lines.

## What keeps it cheap and the page whole

| | |
|---|---|
| **Daily budget** | `MATCHLENS_DAILY_AI_MATCHES` (5) matches a day are explained by the agents on Foundry, within `MATCHLENS_DAILY_MODEL_CALLS` (850) model calls. A match takes about 65 calls for the cards, plus a few for the recap and Spanish. The count is kept in `MATCHLENS_STATE_DIR` and resets at midnight UTC. |
| **Past the budget** | The match is still generated and played; the deterministic rules write the cards, and the screen says so. |
| **One at a time** | One match on the agents at a time; a second viewer's match gets the rules. At most three matches play at once. |
| **Per visitor** | `MATCHLENS_GENERATE_PER_HOUR` (6) new matches an hour from one address. |
| **Foundry slow or down** | The app checks it can sign in before the first minute. A moment that takes over 45 s, or any failure, hands that card and the rest of the match to the rules, labelled "Rules-written" on the card. |
| **Server gone** | A plain static copy of web/ hides the button; the demo matches always play. |

## Running it

```
matchlens-live --web web --agents offline     # no Azure: the rules explain every match
matchlens-live --web web                      # agents on Foundry when AZURE_AI_PROJECT_ENDPOINT is set
```

On Azure Container Apps the app signs in with its managed identity, which needs the **Azure AI
User** role on the Foundry account (`infra/main.bicep` grants it). The deploy workflow sets the
endpoint and the budget on the app.
