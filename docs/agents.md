# The agents

![The under-the-hood panel next to a card explained by the agents on Foundry](img/agents.png)

The Watcher, the specialists and the Explainer ([explainer.md](explainer.md)) also run as a crew of agents on Microsoft Foundry. The models reason, compare and choose. Tools compute every number, and a Verifier written in code checks every choice. The deterministic Explainer is still there as the fallback, and as the offline stand-in for the models.

```
pip install -e ".[foundry]"
az login
export AZURE_AI_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
matchlens-agents out/matches/ash-brk-7 --runner foundry           # the cards, with each agent's reasoning
matchlens-broadcast --demo 6 --agents foundry                     # bundles for the screen, explained by the agents
matchlens-explain-eval --matches 30 --agents foundry              # score the crew against hidden truth
```

`AZURE_AI_MODEL` picks the model deployment (default `gpt-4.1-mini`). Sign-in is Microsoft Entra ID through `DefaultAzureCredential`, so no key is stored anywhere. Without the `foundry` extra, or with `--runner offline`, the same crew runs on the deterministic rules.

## Who does what

For each moment the Watcher raises (a shift, a recovery or an event):

| Agent | Foundry agent | Tool | Job |
|---|---|---|---|
| **Team-play analyst** | `matchlens-team-play` | `investigate_team_play` | How each team's play changed since the anchor. |
| **Player analyst** | `matchlens-players` | `investigate_players` | Which players changed most, and team-wide fatigue. |
| **Substitutions analyst** | `matchlens-substitutions` | `investigate_substitutions` | Each recent substitute against the player he replaced. |
| **Match-events analyst** | `matchlens-match-events` | `investigate_match_events` | Goals, red cards and game state. |
| **Explainer** | `matchlens-explainer` | `check_card` | Chooses the cause and the one or two numbers that show it. |
| **Verifier** | (code) | | Recomputes every number from the tables and enforces the screen rules. |

1. **The four specialists run at the same time.** Each one calls its tool. The tool computes findings from the match tables and posts them to the shared findings board, each with an id (F1, F2, ...). The specialist then says which of its findings matter, or "not me".
2. **The Explainer reads the board.** It also gets a cause menu: only the causes the evidence allows for this moment. For example, a goal can be followed by "the scorers kept pushing", "the other side chased the game" or "no reaction". It picks a cause and up to two finding ids, then calls `check_card` to test its draft before answering.
3. **The Verifier checks the final draft.** It runs the specialists again on the tables, independently of what was posted, and compares every number. It also checks the screen rules:
   - a number must be big enough to see;
   - no metric appears twice;
   - a player's number appears only when the card is about him;
   - a "10 men reshaped" claim needs a stat that shows it.

   A rejected draft goes back to the Explainer once, with the problems listed. A second rejection, or an Explainer that fails, falls back to the deterministic choice.

The models only ever refer to numbers by id. The card is built from the board, so the number on screen is the number the tool computed. A model cannot change a number by retyping it.

**When an agent fails.** A specialist that fails or times out leaves its findings off the board. The Explainer works with what is there, and the card's confidence drops by 0.1 for each missing specialist. Every step is logged on the card under `agents`: each specialist's verdict and note, the Explainer's reason, and each Verifier round. The screen shows this log in its under-the-hood panel (press U).

**On Foundry.** Each role is published once to the project's Agent Service as a prompt agent, with its instructions, model and tool declarations. A new version is published only when the definition changes. Tasks run as those agents through Microsoft Agent Framework (`FoundryAgent`). The tools run in the pipeline, on the match tables.

## The shared board

One record per finding, as in [design.md](design.md) section 5:

```json
{"id": "F7", "agent": "team_play", "claim_type": "team_change", "team": "brk", "metric": "possession",
 "label": "Possession", "before": 41.2, "after": 63.0, "unit": "%", "effect_sd": 2.8, "minutes": 9, "polarity": 1}
```

`effect_sd` measures how unusual the change is against random windows of the same match. `polarity` says whether more of the stat means more control for that team.

## How it scores

On 30 unseen matches (season seed 9000), scored against the generator's hidden truth the same way as [explainer.md](explainer.md):

| | Deterministic Explainer | Agents on Foundry (gpt-4.1-mini) |
|---|---|---|
| Cards per match (before the Director) | 12.2 | 12.2 |
| Shifts matching a hidden swing (random windows: 69%) | 81% | 81% |
| Event shifts backed by a real decision | 84% | 84% |
| Checked cause claims correct | 71% (49 claims) | 70% (43 claims) |
| Cards that fell back to the rules | | 3.6% |
| Model calls, tokens | | 1,826 calls, 3.1M in, 110k out (about $1.40 in all, 5 cents a match) |

The Watcher is the same code in both columns, so the first three rows match by construction. The test is the claims, and the agents hold the same accuracy while making their own choices:
- They call a substitute's impact less often (47 cards against 77) and say the change made no visible difference more often (66 against 38).
- They put fewer cards down to fatigue (14 against 20), at about the same accuracy (79% against 80%).

The truth can't score substitution claims yet, so it can't say whether the agents' extra caution there is right.

Run it with `matchlens-explain-eval --matches 30 --agents foundry`. CI runs the offline crew only, which gives the same cards as the deterministic Explainer.

## Code

- `matchlens/agents/board.py`: the findings board.
- `matchlens/agents/roles.py`: each agent's instructions.
- `matchlens/agents/verifier.py`: the cause menu and the Verifier.
- `matchlens/agents/crew.py`: the crew, and `matchlens-agents`.
- `matchlens/agents/runners.py`: the Foundry and offline runners.

Tests in `tests/test_agents.py` cover the following:
- the offline crew gives the same cards as the deterministic Explainer;
- a rejected draft goes back once and then falls back;
- a fixed draft passes on its second round;
- a failed specialist lowers confidence;
- the Verifier catches a number that no longer matches the tables.
