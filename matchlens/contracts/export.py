"""Generate ``schemas/*.schema.json`` from the contract models.

matchlens-schemas            # write the schemas
matchlens-schemas --check    # exit 1 if the committed schemas are out of date (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from .common import SCHEMA_VERSION
from .cues import Cue, CueTrack, FactBox
from .events import MatchEvent
from .frames import Frame
from .league import League
from .match import MatchMeta
from .moment import Moment
from .season import Season

SCHEMAS: dict[str, type[BaseModel]] = {
    "match_event": MatchEvent,
    "frame": Frame,
    "match_meta": MatchMeta,
    "moment": Moment,
    "fact_box": FactBox,
    "cue": Cue,
    "cue_track": CueTrack,
    "league": League,
    "season": Season,
}

BASE_ID = "https://github.com/ttman12/matchlens-pl-hackathon/schemas/"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "schemas"


def render(name: str, model: type[BaseModel]) -> str:
    schema = model.model_json_schema(mode="serialization")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_ID}{name}.schema.json",
        "x-schema-version": SCHEMA_VERSION,
        **schema,
    }
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="fail if schemas are stale")
    args = parser.parse_args(argv)

    stale: list[str] = []
    args.out.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMAS.items():
        path = args.out / f"{name}.schema.json"
        text = render(name, model)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            path.write_text(text, encoding="utf-8")

    if stale:
        print(f"Stale schemas: {', '.join(stale)}. Run `matchlens-schemas`.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
