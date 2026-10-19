# Contributing

## Set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Before you push

```bash
ruff format .
ruff check .
mypy
matchlens-schemas --check
pytest
```

CI runs the same steps on every push and pull request.

## How we work

- **Ownership.** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#who-owns-what) says which
  track owns each folder. Stay inside yours; to change someone else's, open a PR and say so
  in the description.
- **Contracts first.** Every format shared between modules is a model in
  `matchlens/contracts`. Change one in its own PR and regenerate `schemas/` and the sample
  match in the same PR. Details in
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#changing-a-contract).
- **Branches and pull requests.** Work on a branch and open a pull request into `main`.
  Keep each PR to one change a reviewer can follow. CI must be green before merging.
- **Commits.** Imperative subject line under about 72 characters, then a short body saying
  why when it isn't obvious.
- **Tests.** New logic comes with tests. Deterministic parts (simulator, stats, detector,
  director) are tested against the sample match or a fixed seed.

## Rules for content and data

- **Fictional only.** No real league, club, player, stadium or match names or data, and no
  real logos or marks, in code, data, prompts, screenshots or video.
- **No secrets.** Keys and endpoints go in `.env` (git-ignored; see `.env.example`) or in
  Azure configuration, never in the repository.
- **No copyrighted media.** Crowd audio and any other media must be generated or
  royalty-free, with the licence recorded.
