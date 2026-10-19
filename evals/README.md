# evals

Proof that **no unverified number reaches a cue**. Owned by the AGT track.

```bash
pip install -e ".[agents]"
python evals/run_evals.py             # offline, no credentials; CI runs this
python evals/run_evals.py --foundry   # also Foundry evaluators (needs Azure, see below)
```

## Suites

1. **Verifier cases** (`groundedness_cases.jsonl`). 20 hand-written drafts against the
   sample match's goal and card moments. Each cites evidence by a named ref (`shot`,
   `run:ash-09`, `share:ash-08`, `discipline`…) and expects `approved`, `repaired`
   (only a missing citation, which the Verifier adds) or `rejected`. Wrong speeds, a
   2-0 that was 1-0, "three lines" with nothing backing three, an invented player and
   an abusive Club line must all be rejected; rounding (34.3 km/h shown as 34) is fine.
2. **Chaos audits.** The full pipeline runs five times: clean, every lens agent
   misquoting a number, the Pundit killed, every lens agent killed, the Translator
   killed. Each written cue track then goes through the independent audit
   (`matchlens/agents/audit.py`, also `matchlens-evals <match_dir> <out_dir>`):
   - every number in every box, in every language, is backed by an evidence item on
     that box;
   - every evidence item on a box is on the moment record, unchanged;
   - every evidence number is recomputed from the match files and agrees.
   It also fails if a misquoted draft was approved, or if chaos misquoted nothing.
3. **Foundry groundedness** (`--foundry`). Player-lens agents run on Foundry and their
   output is scored by Foundry's built-in groundedness and relevance evaluators, with
   the moment's evidence as context. Needs the settings in `.env.example`. Each run
   prints its pass count per evaluator and a link to the run in the Foundry portal; a
   run that does not complete, or any failed judgment, fails the evals. First run
   (19 Oct 2026, gpt-4.1-mini): 8 of 8 boxes passed groundedness and relevance.

## Adding a case

One JSON object per line: `id`, `moment` (`goal`, `card` or `corner`), `lens`,
`subject`, `headline`, `body`, `cite` (named refs, see `EvidenceLedger.refs`), `expect`.
