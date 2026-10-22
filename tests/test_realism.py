import json

from swing.gen.season import generate_season
from swing.realism.agg import from_events
from swing.realism.gate import TARGETS, TOLERANCE
from swing.realism.metrics import compute


def test_targets_cover_every_metric() -> None:
    real = json.loads(TARGETS.read_text())
    assert set(real) == set(TOLERANCE)


def test_small_season_is_in_the_right_range() -> None:
    season = generate_season(seed=5, limit=24, workers=2)
    r = compute([from_events(m["match_id"], m["home"], m["away"], m["events"]) for m in season])
    real = json.loads(TARGETS.read_text())
    for k in ("passes per team", "pass accuracy", "shots per team", "duels per team", "events per team"):
        assert abs(r[k] - real[k]) <= 3 * (TOLERANCE[k] or 0), k
