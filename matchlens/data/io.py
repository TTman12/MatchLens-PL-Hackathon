"""Read and write matches in the public format (see docs/data-format.md).

A match folder holds match.json, events.jsonl, physical.csv (optional), team_minute.csv and
player_minute.csv. Hidden ground truth from the generator is written to a separate folder so that
nothing reading a match folder can see it.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .aggregate import aggregate

FORMAT_VERSION = "1.0"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.read_text().strip():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_match(
    folder: Path, meta: dict[str, Any], events: list[dict[str, Any]], physical: list[dict[str, Any]] | None = None
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"format_version": FORMAT_VERSION, **meta}
    (folder / "match.json").write_text(json.dumps(meta, indent=1) + "\n")
    with (folder / "events.jsonl").open("w") as f:
        for e in events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    if physical:
        _write_csv(folder / "physical.csv", physical)
    team_rows, player_rows = aggregate(meta, events, physical)
    _write_csv(folder / "team_minute.csv", team_rows)
    _write_csv(folder / "player_minute.csv", player_rows)


def read_match(folder: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (meta, events, physical rows) for any match folder."""
    meta = json.loads((folder / "match.json").read_text())
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines() if line.strip()]
    return meta, events, _read_csv(folder / "physical.csv")
