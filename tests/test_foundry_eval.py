import json
from pathlib import Path

from swing.foundry_eval import NumbersOnCard, card_context, rows, run

DATA = Path(__file__).resolve().parents[1] / "web" / "data"


def _bundles() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(DATA.glob("*.json")) if p.name != "index.json"]


def test_every_line_on_screen_becomes_a_row_with_its_evidence() -> None:
    bundles = _bundles()
    table = rows(bundles)
    cards = [c for b in bundles for c in b["cards"]]
    analysis = [a for c in cards for a in (c.get("analysis") or {}).values() if a and a.get("line")]
    recaps = sum(len((b.get("recap") or {}).get("text") or {}) for b in bundles)
    english = [r for r in table if r["lang"] == "en"]
    assert len(english) == sum(len(c.get("text") or {}) for c in cards) + len(analysis) + recaps
    spanish = [r for r in table if r["lang"] == "es"]
    assert spanish and all(r["agent"].endswith("(es)") and r["query"].endswith("Answer in Spanish.") for r in spanish)
    b = bundles[0]
    c = b["cards"][0]
    ctx = card_context(b, c)
    assert all(s["label"] in ctx and str(s["value"]) in ctx for s in c["stats"])
    assert {r["agent"] for r in english} == {"interpreter", "analyst", "recapper"}


def test_the_code_check_catches_a_number_not_on_the_card() -> None:
    ctx = "Stats on the card:\n- Brackenford: Passes in final third, 2 before -> 6 in 9 min"
    assert NumbersOnCard()(response="Six final-third passes in 9 minutes.", context=ctx)["numbers_on_card"] == 1.0
    out = NumbersOnCard()(response="They have had 14 shots.", context=ctx)
    assert out["numbers_on_card"] == 0.0 and out["numbers_stray"] == "14"


def test_offline_run_writes_the_report(tmp_path: Path) -> None:
    summary = run(DATA, tmp_path, offline=True, limit=None)
    assert summary["groups"]["all"]["lines"] == len(rows(_bundles()))
    assert (tmp_path / "report.md").read_text().startswith("# Foundry evaluation")
