# Featured match

The featured fixture of [the season](../season), played with the `comeback` storyline:
Ashmere 3-2 Brackenford, events and metadata only. The 10 Hz frames (about 45 MB) are
not committed; regenerate the full folder, frames included, with:

```bash
matchlens-sim featured --season-dir data/season --storyline comeback --out out/featured
```

The output is deterministic, so the events written there match these.
