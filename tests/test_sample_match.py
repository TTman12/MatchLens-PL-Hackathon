"""The sample match must validate, hang together, and be reproducible from its script."""

from __future__ import annotations

import math
from collections import Counter
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from matchlens.contracts import (
    FRAME_RATE_HZ,
    CueTrack,
    Frame,
    League,
    MatchEvent,
    MatchMeta,
    Moment,
    Season,
)
from matchlens.contracts.pitch import attacking_direction, to_pitch

from .conftest import SAMPLE, SCHEMAS, load_json

Sample = dict[str, Any]


def test_files_match_the_contracts(sample: Sample) -> None:
    League.model_validate(sample["league"])
    Season.model_validate(sample["season"])
    MatchMeta.model_validate(sample["match"])
    CueTrack.model_validate(sample["cues"])
    for e in sample["events"]:
        MatchEvent.model_validate(e)
    for m in sample["moments"]:
        Moment.model_validate(m)
    for f in sample["frames"]:
        Frame.model_validate(f)


@pytest.mark.parametrize(
    ("schema", "key"),
    [
        ("league", "league"),
        ("season", "season"),
        ("match_meta", "match"),
        ("cue_track", "cues"),
        ("match_event", "events"),
        ("moment", "moments"),
        ("frame", "frames"),
    ],
)
def test_files_match_the_json_schemas(sample: Sample, schema: str, key: str) -> None:
    """Non-Python readers (the web player) rely on the JSON Schemas, so check them too."""
    validator = Draft202012Validator(load_json(SCHEMAS / f"{schema}.schema.json"))
    docs = sample[key] if isinstance(sample[key], list) else [sample[key]]
    if key == "frames":
        docs = docs[:: FRAME_RATE_HZ * 5]
    for doc in docs:
        validator.validate(doc)


def test_frames_are_continuous_at_10_hz(sample: Sample) -> None:
    times = [f["t"] for f in sample["frames"]]
    assert times[0] == 0.0
    steps = {round(b - a, 3) for a, b in pairwise(times)}
    assert steps == {1 / FRAME_RATE_HZ}
    assert all(len(f["players"]) == 22 for f in sample["frames"])


def test_ids_refer_to_real_things(sample: Sample) -> None:
    meta = sample["match"]
    starters = {e["player_id"] for side in ("home", "away") for e in meta[side]["starting"]}
    squads = {p["player_id"] for c in sample["league"]["clubs"] for p in c["squad"]}
    assert starters <= squads
    event_ids = [e["event_id"] for e in sample["events"]]
    assert len(event_ids) == len(set(event_ids))
    for e in sample["events"]:
        for key in ("player_id", "receiver_id", "related_player_id"):
            assert e.get(key) is None or e[key] in starters, (e["event_id"], key)
    moment_ids = {m["moment_id"] for m in sample["moments"]}
    for m in sample["moments"]:
        for inv in m["involved"]:
            assert set(inv["events"]) <= set(event_ids)
    for cue in sample["cues"]["cues"]:
        assert cue.get("moment_id") is None or cue["moment_id"] in moment_ids


def test_events_are_in_time_order(sample: Sample) -> None:
    times = [e["t"] for e in sample["events"]]
    assert times == sorted(times)


def test_sample_has_the_promised_moments(sample: Sample) -> None:
    types = Counter(e["type"] for e in sample["events"])
    assert types["goal"] == 1
    assert types["corner"] >= 1
    assert types["card"] >= 1
    goal = next(e for e in sample["events"] if e["type"] == "goal")
    build_up = [
        e
        for e in sample["events"]
        if e.get("possession_id") == goal["possession_id"] and e["type"] in {"pass", "carry"}
    ]
    assert len(build_up) >= 5, "the goal needs a real build-up"


def test_actors_are_on_the_ball(sample: Sample) -> None:
    """Whoever an event names is where the event says, in the tracking data, at that time."""
    frames = {round(f["t"], 1): f for f in sample["frames"]}
    home = sample["match"]["home"]["team_id"]
    first = sample["match"]["home_attacks_in_period_1"]
    for e in sample["events"]:
        if "start" not in e or "player_id" not in e or e["type"] in {"card", "goal"}:
            continue
        direction = attacking_direction(first, e["team_id"] == home, e["period"])
        where = to_pitch(tuple(e["start"]), direction)
        frame = frames[round(e["t"], 1)]
        assert math.dist(where, frame["players"][e["player_id"]][:2]) < 1.5, e["event_id"]
        if e["type"] not in {"pressure", "tackle", "interception", "foul"}:
            assert math.dist(where, frame["ball"][:2]) < 1.5, e["event_id"]


def test_player_speeds_are_human(sample: Sample) -> None:
    fastest = max(
        math.hypot(vx, vy) * 3.6 for f in sample["frames"] for _, _, vx, vy in f["players"].values()
    )
    assert 28 < fastest < 37


def test_evidence_matches_its_source(sample: Sample) -> None:
    """The rule the Verifier enforces, checked on the hand-written example."""
    events = {e["event_id"]: e for e in sample["events"]}
    goal = next(m for m in sample["moments"] if m["type"] == "goal")
    for item in goal["evidence"]:
        if item["source"] in events:
            qualifiers = events[item["source"]]["qualifiers"]
            for key, value in item["numbers"].items():
                if key in qualifiers:
                    assert qualifiers[key] == value, (item["id"], key)
    scorer = goal["involved"][0]
    assert scorer["role"] == "scorer"
    assert scorer["top_speed_kmh"] > 30, "the speed badge threshold is about 30 km/h"


def test_season_table_adds_up(sample: Sample) -> None:
    table = sample["season"]["table"]
    assert sum(r["won"] for r in table) == sum(r["lost"] for r in table)
    assert sum(r["goals_for"] for r in table) == sum(r["goals_against"] for r in table)
    for r in table:
        assert r["points"] == 3 * r["won"] + r["drawn"]
        assert r["played"] == r["won"] + r["drawn"] + r["lost"]
    played = [f for f in sample["season"]["fixtures"] if f["status"] == "played"]
    assert sum(f["score"]["home"] + f["score"]["away"] for f in played) == sum(
        r["goals_for"] for r in table
    )


def test_sample_is_reproducible(sample_builder: ModuleType, tmp_path: Path) -> None:
    sample_builder.build(tmp_path)
    for path in sorted(SAMPLE.iterdir()):
        if path.suffix in {".json", ".jsonl"}:
            assert (tmp_path / path.name).read_bytes() == path.read_bytes(), (
                f"{path.name} is stale: run python scripts/make_sample_match.py"
            )
