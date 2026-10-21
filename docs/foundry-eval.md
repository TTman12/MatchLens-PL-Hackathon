# Foundry evaluation results

The latest full run of `matchlens-foundry-eval` covered every line on the live screen: 448 lines from the six demo matches in `web/data`. That is each card's read (the Interpreter), each "what next" line (the Analyst) and each full-time headline (the Recapper), for the neutral viewer and for each club's fans, in English and in Spanish.

- **Run:** GitHub Actions [run 39682021221](https://github.com/TTman12/MatchLens-PL-Hackathon/actions/runs/39682021221), 21 Oct 2026, judged by `gpt-4.1-mini`. It is logged to the Foundry project's Evaluations page as run `753cc753-a0c6-4d62-a823-63c934f8b547`.
- **Judges:**
  - Groundedness, relevance and coherence come from the Azure AI Evaluation SDK and are scored 1 to 5. A line passes a judge at 3 or more.
  - "Numbers on card" is a code check that every number in the line is on the card.

| Group | Lines | Numbers on card | Groundedness (mean, pass) | Relevance (mean, pass) | Coherence (mean, pass) |
|---|---|---|---|---|---|
| **all** | 448 | 100% | 4.86, 97% | 4.10, 99% | 4.01, 100% |
| interpreter | 114 | 100% | 4.81, 95% | 3.83, 97% | 3.97, 100% |
| interpreter (es) | 114 | 100% | 4.79, 94% | 3.82, 97% | 4.01, 100% |
| analyst | 92 | 100% | 4.97, 100% | 4.11, 100% | 3.98, 100% |
| analyst (es) | 92 | 100% | 4.97, 100% | 4.51, 100% | 4.08, 100% |
| recapper | 18 | 100% | 4.72, 94% | 4.61, 100% | 4.11, 100% |
| recapper (es) | 18 | 100% | 4.72, 94% | 4.89, 100% | 4.06, 100% |

The run's report, an artifact of that GitHub Actions run, also splits each group by viewer (neutral against club fans).

## What the scores say, honestly

- **The numbers are always right, by construction.** Every number on screen comes from a tool, and code checks every line before it goes out (the Verifier for cards, the agents' own checks for the lines). That is why the numbers column is 100%. The column confirms the checks work. It doesn't measure the model.
- **The weak spot is spin in club lines.** Most groundedness failures are Interpreter lines written for a club's fans that put a positive spin on bad news. One example is "Despite being a man down, Brackenford remain organised and resilient", when the card shows Ashmere's share of play going from 66% to 97% after the red card. Another is "Brackenford is keeping control with long passes" at a moment when their share was falling. Club lines pass groundedness 93% of the time, against 97% for neutral lines. The Spanish versions of the same lines fail in the same places, so the translation is faithful, flaws and all.
- **Relevance is the lowest score for the Interpreter (3.8 out of 5).** The judge often marks a one-line read down for not spelling out the full "why". A line that has to fit on a broadcast card is short on purpose.
- **The judge is lenient and related to the writer.** The same model family writes the lines and judges them. In an earlier smoke run it gave groundedness 5 to a line saying a team was "creating more chances" when the card had no chance stat. Treat 4.9 out of 5 as an upper bound. The code checks are the hard guarantee.
- **What we'd do next:** give the Interpreter the rule "a club line may be hopeful, but must not deny what the card shows", then re-run this evaluation to check that the club-line groundedness rate rises.

## Running it

From GitHub, go to Actions > Foundry evaluation > Run workflow. It signs in with OIDC as `matchlens-ci`, which needs the Cognitive Services User role on the Foundry account to log the run.

Locally:

```
pip install -e ".[eval]"
matchlens-foundry-eval web/data
```

Add `--offline` for the code check only.
