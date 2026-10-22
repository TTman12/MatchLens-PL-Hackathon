# Swing

**Everyone can see when the tide turns. Swing shows you why.**

Swing is a team of AI agents that watches every club and player statistic in a football match, minute by minute. When momentum swings, it works out where the change came from (a substitute out-running the player he replaced, a side dropping deeper after a red card, a team chasing the game) and puts the answer on screen as a broadcast graphic: one or two numbers, a momentum bar and one plain-English sentence on why it happened, told from your side of the game (your club, or neutral if you don't have one) and in your language. Every number is computed by code and checked again before it airs, so the models choose and explain but can never make a number up.

All match data is synthetic and every club and player is fictional. Built for the Microsoft × Premier League hackathon.

**Try it live:** <https://matchlens-live.blacktree-62621304.eastus2.azurecontainerapps.io> (fan screen). Add `?mode=admin` for the operator screen, where **Generate match** makes a brand-new match and plays it through the agents on Microsoft Foundry while you watch.

![The broadcast screen: a card on a substitute's running, the momentum bar and the club stats](docs/img/broadcast.png)

## Testing it

Free, with no sign-in, until judging ends. Swing is built for a **desktop browser** (Chrome or Edge, a 16:9 window).

| Link | What to try |
| --- | --- |
| [Fan screen](https://matchlens-live.blacktree-62621304.eastus2.azurecontainerapps.io) | Pick a club and a player, press play. Six prebuilt matches, no limits. |
| [Admin screen](https://matchlens-live.blacktree-62621304.eastus2.azurecontainerapps.io/?mode=admin) | Club and player stats, the Agents tab, the match list and **Generate match**: a brand-new match played through the agents on Microsoft Foundry (about 3 minutes). |
| [Fault drill](https://matchlens-live.blacktree-62621304.eastus2.azurecontainerapps.io/?mode=admin&tab=agents&drill=explainer) | Press Generate match with the Explainer knocked out, and watch the chain recover on the Agents tab. Pick another agent in the Fault drill menu. |

**Limits on Generate match.** 10 matches a day across the whole site are explained by the agents (the count resets at midnight UTC), one at a time. Each visitor can start 6 matches and 3 fault drills an hour. Past the daily 10, or while another viewer's match has the agents, a match still plays in full and the deterministic rules write its cards, labelled "Rules-written" on screen. The first visit after a quiet spell takes a few seconds while the app starts.

## Contents

- [Testing it](#testing-it)
- [The problem](#the-problem)
- [The five stages](#the-five-stages)
- [Architecture and the agents' chain of command](#architecture-and-the-agents-chain-of-command)
- [What a viewer sees](#what-a-viewer-sees)
- [Follow a player](#follow-a-player)
- [Built on Microsoft](#built-on-microsoft)
- [Run it locally (offline, no Azure)](#run-it-locally-offline-no-azure)
- [Proof it works](#proof-it-works)
- [Synthetic data](#synthetic-data)
- [Honest limits](#honest-limits)
- [Docs](#docs)

## The problem

A broadcast shows possession and shots, and anyone watching can tell which side is on top. What nobody shows is *why* the game turned. Real matches swing about five or six times, and about 30% of those swings follow no goal, card or substitution at all (measured on a full real season, [docs/research](docs/research/real-momentum-patterns.md)). Explaining them needs every stat watched at once, compared against the match so far, and turned into something a fan can read in two seconds while the ball is in play. That is too much for a person on a live feed, and a single chatbot invents numbers. Swing splits the job between specialist agents, with code in charge of every number and of what reaches the screen.

## The five stages

The brief asks for one pipeline with five stages. This is where each one lives.

| Stage | What Swing does | Code |
| --- | --- | --- |
| **1. Ingest** | Takes a match a minute at a time: per-minute club and player tables plus key events (goals, cards, subs), from our generator or from any provider, with a small file mapping its column names onto ours. Nothing later than the current minute exists. | `swing/ingest/`, `swing/gen/` |
| **2. Interpret** | Aggregates 24 club stats and 14 player stats (possession, PPDA, defending height, duels won, xG, distance, sprints and more). The Watcher, which is plain code, keeps a running momentum scale and flags the minute something needs explaining: a momentum shift, a recovery after a dip, or a key event. It only ever uses the minutes already played. | `swing/data/`, `swing/explain/watcher.py` |
| **3. Explain** | Four specialist agents investigate in parallel and post findings to a shared board. The Explainer picks the cause and the one or two numbers that show it. A Verifier in code recomputes every number. | `swing/agents/`, `swing/explain/` |
| **4. Render** | A Director in code decides which explanations are good enough, and spaced out enough, to go on screen. Each card is a timed, machine-readable JSON cue, drawn as a lower-third over the feed with a momentum bar, timeline and notifications. | `swing/explain/director.py`, `swing/broadcast/`, `web/` |
| **5. Personalise** | Your club, your player, your language (English or Spanish), and a simple card that expands into the analyst's table. Each card's line is written once for a neutral and once for each club's fans, and every viewer is shown the version for their side. A full-time recap closes the match. | `swing/agents/interpreter.py`, `analyst.py`, `recapper.py`, `translator.py`, `web/` |

## Architecture and the agents' chain of command

![Swing architecture: ingest, interpret, explain, render and personalise, with code deciding and Foundry agents choosing and writing](docs/img/architecture.svg)

**Code is in charge; the agents choose and write.** Code decides *when* to act (the Watcher), *what is allowed* (the Verifier and the checks on every line) and *what reaches the screen* (the Director). The agents on Microsoft Foundry do the judgement: which findings matter, what caused the swing, and what it means for each set of fans.

| Agent | Kind | Job |
| --- | --- | --- |
| **Watcher** | code | Flags the minute something needs explaining: a momentum shift, a recovery after a dip, or a key event (goal, red card, substitution, half-time). It checks every minute from 15', using only the minutes already played, and never changes its mind later. |
| **Team-play analyst** | Foundry agent + tool | How each side's play changed since the moment began, across 21 team stats. |
| **Player analyst** | Foundry agent + tool | The biggest individual movers on each side, and a team-wide fatigue fade. |
| **Substitutions analyst** | Foundry agent + tool | Each substitute against the player he replaced. Allowed to say "not me". |
| **Match-events analyst** | Foundry agent + tool | Goals, red cards and game state: a side chasing the game, a ten-man reshape. |
| **Explainer** | Foundry agent | Reads the shared board and picks a cause from those the evidence allows, plus one or two finding ids. Tests its draft with a `check_card` tool. |
| **Verifier** | code | Re-runs the specialists on the tables and compares every number, then enforces the screen rules. A rejected draft goes back once; a second miss falls back to the rules' card. |
| **Director** | code | The match's editor. It sees every card the agents produce (about 12 a match) and puts up only a few (about 5 or 6): at least 10 minutes apart, at most 4 a half, never before 15', and never one with a confidence below 45%. A goal or red card can break the 10-minute gap. It decides as each card arrives and never waits for a better one, so it behaves the same live as on a replay. |
| **Interpreter** | Foundry agent | One sentence per card on what the numbers mean for the game: one for a neutral and one for each club's fans (three in all). It is written once and every viewer sees the version for their side, so the model cost doesn't grow with the audience. No numbers, nothing the data can't see. |
| **Analyst** | Foundry agent | The "Swing analysis" card: what each club could do about it, picked from 18 levers that a stat in the match backs. |
| **Recapper** | Foundry agent | The full-time headline, once for a neutral and once for each club, from the result and how the match went. |
| **Translator** | Foundry agent | Every line in Spanish, written once and shared by all viewers, checked in code so no name or number changes. |

**Shared state and handoffs.** The four specialists never see each other's prompts; they meet on the findings board, where every number is a tool's output with an id. Models only refer to numbers by id, so a model can't change a number by retyping it.

**When something fails.** A specialist that fails or times out leaves its findings off the board; the Explainer works with what is there and the card's confidence drops. A rejected draft gets one retry with its problems listed. A line flagged by Azure AI Content Safety, or one that breaks a check, goes back once and then is replaced by the rules' line. If Foundry is slow (over 45 s on a moment) or down, the deterministic rules take over and the card says "Rules-written". The screen never goes blank. Each step is logged on the card and shown on the admin screen's Agents tab, and every run is one trace in Application Insights.

More: [docs/agents.md](docs/agents.md) (the crew, the board, scores against the hidden truth) and [docs/explainer.md](docs/explainer.md) (the Watcher, the specialists and what stats can and can't tell you).

## What a viewer sees

| | |
| --- | --- |
| ![The fan screen: club crests and the squad on a pitch](docs/img/user-screen.png) | ![The admin screen: stats, the agents and Generate match](docs/img/admin-screen.png) |
| **Fan screen.** Pick your club from its crest and your player from the squad laid out on a pitch. Video-player controls along the bottom. | **Admin screen** (`?mode=admin`). Club and player stats, what each agent did for the card on screen, the match list and Generate match. |
| ![A card expanded into the analyst's table](docs/img/expanded.png) | ![The Swing analysis card](docs/img/analysis.png) |
| **Cards that expand.** A card starts simple: the anchor ("Since Dunmoor goal 25'" or "Last 7 minutes"), one line, one big number. Expand opens the cause, momentum before and now, and four stats for both clubs. | **Swing analysis.** After a card: "How Dunmoor win it back", or how the side on top keeps it going. Your club's, if you have one. |
| ![A goal notification](docs/img/note-goal.png) | ![Generate match at full time](docs/img/generate-match-ft.png) |
| **Notifications** for goals, every substitution, red cards and momentum shifts, so a card never arrives cold. | **Generate match** plays a brand-new, never-seen match through the agents a minute at a time, then the full-time recap. |

Also: the **full-time recap** (who had each quarter-hour, the three turning points, a standout per club), **full screen**, and **Spanish** for every label and line. Details in [docs/broadcast.md](docs/broadcast.md).

## Follow a player

Swing explains a match at two levels that feed each other. The team level shows when momentum swings and why. The player level shows who made it happen. They are one product because they come from the same agents' work: the Player and Substitutions analysts that help explain every swing also name the players behind it.

![A momentum card naming the player who drove the swing, with the followed player's part in it](docs/img/swing-players.png)

- **Driven by, on every card.** Under each swing, the one or two players on the side that took over whose own output rose most since it started ("Y. Dunanu · defensive actions 0 → 5"), or the substitute against the man he replaced. Tap one to follow him.
- **Your player's part in each swing.** Follow a player and every card checks whether he is part of that swing, on either side: "Your player: T. Gorrelli dropped off as Brackenford took over · touches 8 → 1", or "is driving this swing".
- **His match, all the way through.** A strip with his touches, passes and distance, name tags when he reaches milestones (5 and 10 km, 10, 20 and 30 sprints, 25, 50 and 75 passes, and so on), as broadcasters tag players, and his moments on the timeline.
- **His part in the swings at full time.** The recap adds "In 2 of 6 swings", with what he did in each (dropped off at 45+3', drove at 83'), next to where he ranked in his team.

So the same agents' work reaches the analyst reading the tactics and the fan who only cares about one player. Every number is counted from the match tables: a player is named only when his own stats changed clearly (two standard deviations or more against his match so far) in the same direction as the swing.

<!-- BEGIN: Built on Microsoft. This section is owned by the Microsoft stack work (services, evaluation scores, MCP server). Edit it there; the rest of the README links to it by its heading. -->
## Built on Microsoft

Every service below is used by the live product or by the pipeline that builds and checks it. Each was checked against the live site, the GitHub Actions runs or the deployed configuration on 22 Oct 2026.

| Service | Where | What it does |
| --- | --- | --- |
| **Microsoft Foundry Agent Service** | `swing/agents/runners.py` | Nine prompt agents are published to the Foundry project and versioned: `matchlens-team-play`, `-players`, `-substitutions`, `-match-events`, `-explainer`, `-interpreter`, `-analyst`, `-recapper` and `-translator`. A new version is published only when an agent's definition changes. (The agents keep `matchlens-`, the project's working name, as their Foundry prefix.) |
| **Microsoft Agent Framework** (Python) | `swing/agents/runners.py`, `crew.py` | Runs each agent and its tool calls. Four specialists run in parallel on a shared findings board, then the Explainer, then the Interpreter and Analyst. |
| **Model Context Protocol** server | `swing/agents/mcp_server.py` | The agents' tools are served by the Swing MCP server: when a specialist or the Explainer calls a tool, the call goes over MCP to the server, which computes from the match tables and reads or writes the findings board. A failed call runs the tool directly. `swing-mcp out/matches` serves the same tools on stdio to any MCP client. |
| **Foundry Models: Azure OpenAI `gpt-4.1-mini`** | the project's model deployment | The model behind every agent, and the judge for the evaluations. |
| **Foundry Evaluations** (Azure AI Evaluation SDK) | `swing/foundry_eval.py`, `.github/workflows/foundry-eval.yml` | Scores every on-screen line for groundedness, relevance and coherence, plus a code check on numbers. The run is logged to the project's Evaluations page. Latest run, 448 lines in English and Spanish: groundedness 4.86 (97% pass), relevance 4.10, coherence 4.01, numbers on card 100%. The weak spot is spin in club-fan lines. Full results and caveats are in [docs/foundry-eval.md](docs/foundry-eval.md). |
| **Azure AI Content Safety** | `swing/agents/safety.py` | Screens every line the Interpreter, Analyst and Recapper write before it can go on air. A flagged line is sent back to the agent, then replaced by the rule-written line. |
| **Azure Monitor Application Insights**, via **OpenTelemetry** | `swing/telemetry.py` | One trace per match. It covers the Watcher, each moment, specialist, Explainer round and Verifier check, with Agent Framework's agent and model spans underneath. The traces show on the Foundry project's Tracing page. |
| **Azure Container Apps** | `infra/main.bicep`, `Dockerfile`, `swing/live` | Hosts the live site and Generate match, which plays brand-new matches through the agents on Foundry with the app's managed identity. It scales to zero between viewers, and every deploy checks the site's `/healthz` before it counts as passed. |
| **Azure Linux** container image | `Dockerfile` | The base image for the site (`mcr.microsoft.com/azurelinux/base/python`). |
| **Azure Monitor Log Analytics** | `infra/main.bicep` | Collects the container app's logs. |
| **Microsoft Entra ID** | everywhere | There are no keys anywhere. Locally and in Cloud Shell, `DefaultAzureCredential` signs in. The app uses a managed identity. GitHub Actions signs in with **workload identity federation (OIDC)**. |
| **GitHub Actions** and **GitHub Container Registry** | `.github/workflows/` | Tests, a realism gate and the Explainer score on every PR. Builds the image, deploys it to Container Apps over OIDC, runs Foundry evaluations and lints the Bicep. |
| **Bicep** and the **Azure Developer CLI** | `infra/`, `azure.yaml` | The Azure setup as code. The live environment was set up from `infra/main.bicep`, and every PR compiles and lints it. `azure.yaml` lets `azd provision` stand up a new environment, Foundry included (written for that, not yet run from scratch). |
| **Azure Cost Management** budget | `infra/main.bicep` | A $20 monthly budget on the resource group, with email alerts. |

The code can also send the Spanish lines through **Azure AI Translator** (`swing/agents/translator.py`, `--translator azure`), but the live site and the demo matches use the Translator agent, so it isn't listed above.
<!-- END: Built on Microsoft -->

## Run it locally (offline, no Azure)

Python 3.11 or later. Everything below runs with no Azure account and no network: the same crew runs on deterministic rules in place of the models.

```
pip install -e ".[dev]"

(cd web && python3 -m http.server 8000)                # the screen with its six prebuilt matches: http://localhost:8000

swing-gen match --home ash --away brk --seed 7     # one fictional match: events, minute tables, hidden truth
swing-explain out/matches/ash-brk-7                # the cards that would go on screen, in the terminal

cp -r web out/site                                     # a copy of the screen for your own matches
swing-broadcast --demo 6 --out out/site/data       # six fresh matches explained by the rules
(cd out/site && python3 -m http.server 8001)           # http://localhost:8001 (add ?mode=admin)
```

Generate match and the live feed, still offline:

```
swing-live --web web --agents offline              # the site plus Generate match, at http://localhost:8000
swing-feed unseen                                  # the unseen-match test (below)
pytest -q                                              # 90 tests
```

With Microsoft Foundry (`pip install -e ".[foundry]"`, `az login`, and `AZURE_AI_PROJECT_ENDPOINT` set to your project):

```
swing-agents out/matches/ash-brk-7 --runner foundry           # the cards, with each agent's reasoning
swing-broadcast --demo 6 --out web/data --agents foundry      # bundles explained by the agents
swing-live --web web                                          # Generate match on the agents
```

The whole Azure setup is Bicep in `infra/` (`azd provision` stands it up from nothing). See [docs/agents.md](docs/agents.md) and [docs/generate-match.md](docs/generate-match.md).

## Proof it works

Because the generator records *why* each match went the way it did (hidden from the agents), the explanations can be scored against the truth, not just eyeballed.

| Check | Result | Where |
| --- | --- | --- |
| **Realism gate:** a generated season against a real season (public research data, see [Synthetic data](#synthetic-data)) | 31 of 31 numbers within tolerance (passes, shots, goals, cards, subs, shifts per match, the share of shifts with no trigger, the substitute boost, the late-game dip ...) | [docs/realism.md](docs/realism.md), CI job `realism` |
| **Shifts that match a real swing** in the hidden state | 82% (random windows: 69%), on 380 unseen matches | [docs/explainer.md](docs/explainer.md), CI job `explainer` |
| **Cause claims that are right** | 73% of 533 checked claims (rules); 70% for the agents on Foundry on 30 unseen matches, about 5 cents a match | [docs/agents.md](docs/agents.md) |
| **Unseen-match test:** fresh seeds and pairings, sent only as a provider's renamed per-minute feed | Tables rebuilt exactly 30/30; 295 of 295 on-screen numbers recompute; live run identical to the one-go run 30/30 | [docs/live-feed.md](docs/live-feed.md), CI job `unseen` |
| **Generate match** on the live site | A fresh match plays through the Foundry agents in about 3 minutes (about 75 model calls), within a daily budget of 10 AI matches | [docs/generate-match.md](docs/generate-match.md) |

CI runs ruff, strict mypy, the tests, the realism gate, the explainer score and the unseen-match test on every pull request.

## Synthetic data

- **Every match on screen is generated; no real match data is shipped.** The clubs and their squads are fictional (`data/league.json`), the crests are drawn by the page from each club's colours, and no league or club marks appear.
- **How it stays realistic.** To make generated matches behave like real football, `research/learn_priors.py` read one public research dataset once: the Wyscout event data for the 2017-18 Premier League season, published openly by Pappalardo et al. (2019, *Scientific Data* 6:236, [figshare](https://doi.org/10.6084/m9.figshare.c.4415000)) under CC BY 4.0, which allows reuse with credit. It kept only aggregate probability tables (`swing/gen/priors.json.gz`): which action follows which by pitch zone, pass lengths and success, timing, an xG model, card and substitution rates. No real match, club, player or event is stored, and the raw data is never committed or shipped. The same season gives the realism gate its targets (averages such as passes per team and shifts per match, `swing/realism/targets.json`) and the momentum findings in [docs/research](docs/research/real-momentum-patterns.md).
- **How it's generated.** The engine plays a match action by action from those tables, steered by each team's plan (block height, pressing, directness and more), player quality, fatigue and a drifting ebb and flow. A coaching layer changes plans after some events and sometimes for no reason, and logs every decision as hidden truth. Momentum is never written directly: it comes out of the stats. See [docs/generator.md](docs/generator.md).
- **Distance and sprints are modelled**, and marked so on screen.
- **Any match in the format works.** The format is published in [docs/data-format.md](docs/data-format.md), and the feed adapter takes another provider's column names ([docs/live-feed.md](docs/live-feed.md)).

## Honest limits

- **A cause is an inference.** About 70% of spontaneous swings have no change of plan behind them at all, so for most of those the card shows *what* changed in play (duels won, defending height, shots) rather than claiming an instruction nobody can see. Checked cause claims are right about 70 to 73% of the time, and red-card claims are too few to tune.
- **Substitution claims can't be scored yet:** the hidden truth doesn't say whether a substitute made the difference.
- **Tuned on synthetic data.** The effect sizes (`swing/explain/calibration.json`) were fitted on generated matches; a real feed would need them refitted, and would have no hidden truth to score causes against.
- **The live site plays prebuilt matches** so viewers never spend model calls. Generate match is the live path on Foundry, capped at 10 AI matches a day; past that, the rules explain the match and the screen says so.
- **Not built:** auto-eventing from video, ball and shot speed, and a pass difficulty rating. The stadium is an AI-generated still of a fictional ground with no marks, standing in for the match video.
- **Two languages so far:** English and Spanish. A third would need the Translator's check and the rules' fallback lines written for that language.

## Docs

- [docs/design.md](docs/design.md): the design and the decisions behind it.
- [docs/agents.md](docs/agents.md): the agent crew on Microsoft Foundry, the shared board, the Verifier, Content Safety, evaluations and tracing.
- [docs/explainer.md](docs/explainer.md): the Watcher, the specialists and the Explainer, what stats can and can't tell you, and how well it scores.
- [docs/broadcast.md](docs/broadcast.md): the fan and admin screens, the cards, notifications, the recap, follow-a-player, and the Director.
- [docs/live-feed.md](docs/live-feed.md): taking a match from another provider's feed, and the unseen-match test.
- [docs/generate-match.md](docs/generate-match.md): Generate match on the live site.
- [docs/generator.md](docs/generator.md) and [docs/realism.md](docs/realism.md): the synthetic match generator and its realism gate.
- [docs/data-format.md](docs/data-format.md): the match format.
- [docs/research/](docs/research/): which football stats exist and what each reveals, and what 380 real matches show about momentum.

## Licence

MIT. See [LICENSE](LICENSE).
