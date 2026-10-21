# MatchLens

**Everyone can see when the tide turns. MatchLens shows why.**

MatchLens watches every team and player statistic minute by minute. When a match changes, it finds out where the change came from and puts it on screen as a broadcast graphic: one or two numbers and a momentum bar, with no sentences. The change can follow an event (a red card, a substitution, a goal) or happen with no event at all (tiredness, a duel battle turning, the ordinary ebb and flow).

It is a fresh start for the Microsoft × Premier League hackathon. All match data is synthetic and the clubs are fictional.

## Status

- **Synthetic match generator:** built, and passes the realism gate. A full generated season matches the real 2017-18 Premier League on all 31 numbers checked ([docs/realism.md](docs/realism.md)).
- **Watcher, specialists and Explainer:** built as deterministic tools that work on any match in the public format. Scored against the hidden truth on unseen matches ([docs/explainer.md](docs/explainer.md)).
- **Broadcast screen:** score and clock, an always-on momentum scale, a timeline with the momentum history, and pop-up cards chosen by a Director ([docs/broadcast.md](docs/broadcast.md)).
- **Agents on Microsoft Foundry:** four specialist agents, an Explainer agent and a Verifier share a findings board. Tools compute every number; the models choose; the Verifier rechecks every number against the tables ([docs/agents.md](docs/agents.md)).
- **Next:** a stadium still, then redeploy the live site and record the demo.

![The broadcast screen](docs/img/broadcast.png)

## Built on Microsoft

Every service below is used by code in this repo. Nothing is listed that the code doesn't use.

| Service | Where | What it does |
| --- | --- | --- |
| **Microsoft Foundry Agent Service** | `matchlens/agents/runners.py` | Seven prompt agents are published to the Foundry project and versioned: `matchlens-team-play`, `-players`, `-substitutions`, `-match-events`, `-explainer`, `-interpreter` and `-analyst`. A new version is published only when an agent's definition changes. |
| **Microsoft Agent Framework** (Python) | `matchlens/agents/runners.py`, `crew.py` | Runs each agent and its tool calls. Four specialists run in parallel on a shared findings board, then the Explainer, then the Interpreter and Analyst. |
| **Foundry Models: Azure OpenAI `gpt-4.1-mini`** | the project's model deployment | The model behind every agent, and the judge for the evaluations. |
| **Foundry Evaluations** (Azure AI Evaluation SDK) | `matchlens/foundry_eval.py`, `.github/workflows/foundry-eval.yml` | Scores every on-screen line for groundedness, relevance and coherence, plus a code check on numbers. The run is logged to the project's Evaluations page. |
| **Azure AI Content Safety** | `matchlens/agents/safety.py` | Screens every line the agents write before it can go on air. A flagged line is sent back to the agent, then replaced by the rule-written line. |
| **Azure Monitor Application Insights**, via **OpenTelemetry** | `matchlens/telemetry.py` | One trace per match. It covers the Watcher, each moment, specialist, Explainer round and Verifier check, with Agent Framework's agent and model spans underneath. The traces show on the Foundry project's Tracing page. |
| **Azure Container Apps** | `infra/main.bicep`, `Dockerfile` | Hosts the live site. It scales to zero between viewers and has health probes. |
| **Azure Linux** container image | `Dockerfile` | The base image for the site (`mcr.microsoft.com/azurelinux/base/python`). |
| **Azure Monitor Log Analytics** | `infra/main.bicep` | Collects the container app's logs. |
| **Microsoft Entra ID** | everywhere | There are no keys anywhere. Locally and in Cloud Shell, `DefaultAzureCredential` signs in. The app uses a managed identity. GitHub Actions signs in with **workload identity federation (OIDC)**. |
| **GitHub Actions** and **GitHub Container Registry** | `.github/workflows/` | Tests, a realism gate and the Explainer score on every PR. Builds the image, deploys it to Container Apps over OIDC, runs Foundry evaluations and lints the Bicep. |
| **Bicep** and the **Azure Developer CLI** | `infra/`, `azure.yaml` | The whole Azure setup as code. `azd provision` can stand it up from nothing, Foundry included. |
| **Azure Cost Management** budget | `infra/main.bicep` | A $20 monthly budget on the resource group, with email alerts. |

```
pip install -e ".[dev]"
matchlens-gen match --home ash --away brk --seed 7   # one match: events, minute tables, physical, hidden truth
matchlens-explain out/matches/ash-brk-7              # the cards that would go on screen
matchlens-broadcast --demo 6 && (cd web && python3 -m http.server 8000)   # the screen, at localhost:8000
matchlens-agents out/matches/ash-brk-7 --runner foundry   # the agent crew on Foundry (pip install -e ".[foundry]")
matchlens-realism                                     # generate 380 matches and check them against the real season
matchlens-explain-eval                                # score the explainer against hidden truth on unseen matches
pytest -q
```

## Docs

- [docs/design.md](docs/design.md): the design, covering the two modes, the agents, the graphic contract, the scoring and the decisions so far.
- [docs/data-format.md](docs/data-format.md): the match format any match can be fed in as.
- [docs/generator.md](docs/generator.md): how the generator works and what the hidden truth holds.
- [docs/broadcast.md](docs/broadcast.md): the broadcast screen, its controls and the Director.
- [docs/explainer.md](docs/explainer.md): the Watcher, the specialists and the Explainer, what stats can and can't tell you, and how well it scores.
- [docs/agents.md](docs/agents.md): the agent crew on Microsoft Foundry, the shared findings board and the Verifier.
- [docs/research/](docs/research/): which football stats exist and what each one reveals, plus what 380 real matches show about momentum shifts.

## Build order

1. ~~Synthetic match generator, gated on a realism test against the real-season patterns.~~ Done.
2. ~~A watcher that spots shifts, plus specialists that investigate them.~~ Done.
3. ~~Broadcast graphics: a momentum scale, an event timeline, and the event, spontaneous and recovery cards.~~ Done, apart from the stadium still.
4. ~~Specialists as Foundry agents, with an LLM Explainer and a Verifier.~~ Done.

## Research data

`research/` holds the scripts that measured the real-season patterns, and `learn_priors.py`, which turns that season into the generator's aggregate tables (`matchlens/gen/priors.json.gz`). They read the public Wyscout event dataset (Pappalardo et al., 2019, *Scientific Data* 6:236, [figshare](https://doi.org/10.6084/m9.figshare.c.4415000), CC BY 4.0). That data is downloaded on demand to measure patterns only. None of it is committed or shipped.

## Licence

MIT. See [LICENSE](LICENSE).
