import json
import shutil
from pathlib import Path

from matchlens.explain import evaluate
from matchlens.explain.explainer import explain_match
from matchlens.explain.match import load
from matchlens.explain.watcher import SETTLE
from matchlens.gen import generate_match
from matchlens.gen.cli import write_one


def _write(tmp: Path, home: str, away: str, seed: int) -> Path:
    m = generate_match(home, away, seed)
    return write_one(tmp, m.match_id, m.home, m.away, seed, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes)


def test_cards_never_use_later_minutes(tmp_path: Path) -> None:
    md = load(_write(tmp_path, "ash", "brk", 21))
    full = explain_match(md)["cards"]
    for cut in (40, 70):
        early = [c for c in full if c["at"] <= cut]
        live = [c for c in explain_match(md.until(cut))["cards"] if c["at"] <= cut]
        assert early == live


def test_nothing_before_the_settling_period(tmp_path: Path) -> None:
    for seed in (3, 4):
        cards = explain_match(load(_write(tmp_path, "cal", "ash", seed)))["cards"]
        assert cards
        assert all(c["at"] >= SETTLE for c in cards)
        for c in cards:
            assert 1 <= len(c["stats"]) <= 2 or c["cause"]["kind"].endswith("no_change") or not c["show"]


def test_any_match_folder_with_only_the_required_files(tmp_path: Path) -> None:
    src = _write(tmp_path / "gen", "brk", "cal", 8)
    bare = tmp_path / "bare"
    bare.mkdir()
    for f in ("match.json", "events.jsonl"):
        shutil.copy(src / f, bare / f)
    result = explain_match(load(bare))
    assert result["cards"]
    assert all(
        s["label"] not in ("Distance per player", "Sprints") for c in result["cards"] for s in c["stats"] if not s.get("player")
    )


def test_agents_never_read_truth() -> None:
    pkg = Path(evaluate.__file__).parent
    for f in pkg.glob("*.py"):
        if f.name not in ("evaluate.py",):
            text = f.read_text()
            assert '"truth"' not in text and "truth/" not in text and "decisions" not in text, f.name


def test_evaluation_runs(tmp_path: Path) -> None:
    for i, (h, a) in enumerate([("ash", "brk"), ("brk", "cal"), ("cal", "ash")]):
        _write(tmp_path, h, a, 100 + i)
    report = evaluate.evaluate(tmp_path)
    assert report["matches"] == 3
    assert report["shift_cards_per_match"] > 0
    json.dumps(report)
