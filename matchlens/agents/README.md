# matchlens.agents

The agent pipeline: one match in, `moments.json`, `cues.json` and `agent_trace.json` out.

```bash
pip install -e ".[agents]"
matchlens-agents data/sample --out out/sample                # offline, no credentials
matchlens-agents data/sample --out out/sample --chaos kill:pundit --chaos misquote:player
matchlens-evals data/sample out/sample                       # audit the output
matchlens-mcp data/sample --moments out/sample/moments.json  # Match-State MCP server (stdio)
```

## Flow

A Microsoft Agent Framework workflow (`af_workflow.py`) runs once per detected moment:

```
Intake ─┬─ PlayerLens (one agent per contributor, in parallel) ─┐
        ├─ ClubLens   (one agent per club)                       ├─ Verify ─ Direct ─ Translate
        └─ PunditLens                                           ─┘
```

- **Moment Detector** (`detector.py`): goals, cards, corners, big saves, big chances and
  momentum swings from the deterministic stats engine (`matchlens/stats`). It builds the
  moment's **evidence ledger**: every fact a box may state, with an id (`ev1`…), its
  numbers and the data it came from. Contributors, contribution shares (possession
  value added per action) and the win-probability swing (suspense and surprise) are
  computed here, never by a model.
- **Lens agents** (`lenses.py`, prompts in `prompts/`): write a box from the ledger and,
  through tools, look up more facts; anything a tool returns is added to the ledger
  first. Gates decide who needs a box (a card with no ban gets none).
- **Verifier** (`verifier.py`): every number must be backed by a cited evidence item
  (`numbers.py` reads digits, percentages, scorelines, ordinals and number words in
  English and Spanish, with units and rounding). Also checks evidence ids, names, length
  and Club tone (Azure AI Content Safety when configured). Ruling: approved, repaired
  (citation added, or a repair agent rewrites), fallback template, or rejected.
- **Director** (`director.py`): one box per track at a time, 8 per half, 4-minute
  cooldown that goals, red cards and suspensions break, priority = importance ×
  relevance, replays only in dead time, speed badges, a timeline-rail line per moment.
- **Translator** (`translator.py`): Spanish (or any language) with numbers and names
  locked; a translation that changes a number is dropped and the box stays English.
- **Briefs** (`briefs.py`): half-time and full-time Pundit briefs at `period_end`.

## Model providers

Agents never call a model directly; they call a `ModelProvider` (`providers/`):

| `MATCHLENS_PROVIDER` | What runs |
|---|---|
| `offline` (default with no settings) | Deterministic templates, same JSON as the models. Tests and the demo use it. |
| `foundry` (default when `AZURE_AI_PROJECT_ENDPOINT` is set) | Agent Framework `Agent`s on `FoundryChatClient`, signed in with `DefaultAzureCredential`. |

`--chaos kill:<agent>` and `misquote:<agent>` wrap either provider for fault injection.
Each agent call has a timeout and one retry, then falls back to the template, and the
agent trace says so. Settings are read from the environment only; see `.env.example`.

## Azure setup (for the `foundry` provider)

1. A Microsoft Foundry resource with a project. Copy the project endpoint into
   `AZURE_AI_PROJECT_ENDPOINT`.
2. Two model deployments in it: a fast one (`AZURE_AI_MODEL_FAST`, lens agents and
   Translator) and a stronger one (`AZURE_AI_MODEL_STRONG`, Pundit and repairs).
3. The **Azure AI User** role on the project for whoever runs it (`az login` locally, a
   managed identity when deployed).
4. Optional: an Azure AI Content Safety resource (`AZURE_CONTENT_SAFETY_ENDPOINT`, with
   the Cognitive Services User role) and Application Insights connected to the project
   (`APPLICATIONINSIGHTS_CONNECTION_STRING`) for traces in Foundry.
