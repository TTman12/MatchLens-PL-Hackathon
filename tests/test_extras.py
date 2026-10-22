import asyncio
import json
import re
import string
from pathlib import Path
from typing import Any

from swing.agents.recapper import RecapJob, check_recap, write_recap
from swing.agents.runners import OfflineRunner, Usage
from swing.agents.translator import AzureBackend, TranslateJob, check_translation, items, translate, translate_bundle
from swing.broadcast.bundle import build, enriched, finish, redirected
from swing.broadcast.tables import PLAYER_STATS, TEAM_STATS
from swing.explain import director, spanish
from swing.explain.analysis import LEVERS
from swing.explain.follow import THRESHOLDS
from swing.explain.insight import LINES, NO_CHANGE, PLAYER_LINES
from swing.explain.match import load
from swing.explain.metrics import METRICS
from swing.explain.recap import HEADLINES, headlines, pattern
from swing.explain.specialists import PLAYER_STATS as SPECIALIST_STATS
from swing.gen import generate_match
from swing.gen.cli import write_one


def _md(tmp: Path, home: str = "dun", away: str = "ash", seed: int = 34) -> Any:
    m = generate_match(home, away, seed)
    return load(
        write_one(tmp, m.match_id, m.home, m.away, seed, m.events, m.physical.rows, m.manager.decisions, m.manager.minutes)
    )


def _fields(spec: Any) -> set[str]:
    texts = [spec] if isinstance(spec, str) else list(spec.values())
    return {f for t in texts for _, f, _, _ in string.Formatter().parse(t) if f}


class Says:
    """A stand-in model that always gives the same answer."""

    name = "scripted"

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.usage = Usage()
        self.calls = 0

    async def run(self, role: Any, prompt: str, tools: Any, job: Any) -> str:
        self.calls += 1
        return json.dumps(self.answer)

    async def close(self) -> None:
        return None


def test_every_english_template_has_a_spanish_twin_with_the_same_slots() -> None:
    for key, spec in LINES.items():
        assert spanish.LINES[key].keys() == spec.keys(), key
        for lens in spec:
            assert _fields(spanish.LINES[key][lens]) <= _fields(spec[lens]) | {"O", "T"}, (key, lens)
    for key, spec in PLAYER_LINES.items():
        assert spanish.PLAYER_LINES[key].keys() == spec.keys()
    assert spanish.NO_CHANGE.keys() == NO_CHANGE.keys()
    assert {lv.key for lv in LEVERS} == set(spanish.LEVERS)
    for lang in ("en", "es"):
        assert HEADLINES[lang].keys() == HEADLINES["en"].keys()


def test_every_stat_label_the_screen_shows_is_in_spanish() -> None:
    labels = {m.label for m in METRICS} | {label for _, label, *_ in TEAM_STATS + PLAYER_STATS}
    labels |= {label for _, label, *_ in SPECIALIST_STATS} | {"Sprints per player"}
    assert labels <= set(spanish.LABELS)


def test_anchors_read_in_spanish() -> None:
    assert spanish.anchor("Since 63'") == "Desde el 63'"
    assert spanish.anchor("Last 10 minutes") == "Últimos 10 minutos"
    assert spanish.anchor("Since half-time") == "Desde el descanso"
    assert spanish.anchor("Since Dunmoor goal 25'") == "Desde el gol de Dunmoor (25')"
    assert spanish.anchor("Since Ben D. came on") == "Desde que entró Ben D."
    assert spanish.anchor("Since Ashmere double change") == "Desde el doble cambio de Ashmere"


def test_the_bundle_carries_the_recap_follow_detail_and_spanish(tmp_path: Path) -> None:
    md = _md(tmp_path)
    b = build(md)
    r = b["recap"]
    assert r["pattern"]["kind"] in HEADLINES["en"]
    assert set(r["text"]) == {"neutral", *md.teams} == set(r["i18n"]["es"]["text"])
    assert len(r["spells"]) == 6 and all(0 <= s["home"] <= 100 for s in r["spells"])
    assert 1 <= len(r["turning_points"]) <= 3
    assert [tp["at"] for tp in r["turning_points"]] == sorted(tp["at"] for tp in r["turning_points"])
    assert set(r["stars"]) <= set(md.teams)
    for c in b["cards"]:
        assert c["detail"]["rows"] and c["detail"]["cause"] == c["cause"]
        es = c["i18n"]["es"]
        assert es["anchor"].startswith(("Desde", "Últimos"))
        assert set(es["text"]) == set(c["text"])
    assert set(b["follow"]) == {p["id"] for p in b["stats"]["players"]}
    assert set(b["stats"]["last15"]) == set(md.teams)
    assert all(v in b["i18n"]["es"]["labels"].values() for v in ("Posesión", "Tiros"))


def test_the_recap_headlines_from_the_rules_pass_their_own_check(tmp_path: Path) -> None:
    for home, away, seed in (("dun", "ash", 34), ("brk", "cal", 33), ("cal", "dun", 32)):
        md = _md(tmp_path / str(seed), home, away, seed)
        b = build(md)
        r = b["recap"]
        job = RecapJob(r["facts"], r["text"], {p["name"] for p in b["stats"]["players"]})
        assert check_recap(job, r["text"]) == [], r["text"]


def test_the_recap_check_holds_headlines_to_the_result(tmp_path: Path) -> None:
    md = _md(tmp_path)
    b = build(md)
    r = b["recap"]
    names = {p["name"] for p in b["stats"]["players"]}
    job = RecapJob(r["facts"], r["text"], names)
    a, o = md.teams
    win = r["facts"]["result"] != "draw"
    bad = dict(r["text"], neutral=f"{md.short(a)} and {md.short(o)} drew 2-2." if win else f"{md.short(a)} beat {md.short(o)}.")
    problems = check_recap(job, bad)
    assert any("draw" in p or "winner" in p for p in problems)
    assert any("number" in p for p in problems) or not win
    star = next(iter(names))
    assert any(star in p for p in check_recap(job, dict(r["text"], neutral=f"{star} inspired {md.short(a)}.")))


def test_a_bad_recap_falls_back_to_the_rules(tmp_path: Path) -> None:
    md = _md(tmp_path)
    r = build(md)["recap"]
    model = Says({"neutral": "The manager got it right.", **{t: "x" for t in md.teams}})
    text, fallback = asyncio.run(write_recap(model, RecapJob(r["facts"], r["text"], set())))  # type: ignore[arg-type]
    assert fallback and text == r["text"] and model.calls == 2


def test_the_pattern_reads_the_result(tmp_path: Path) -> None:
    md = _md(tmp_path)
    pat = pattern(md, [50.0] * (md.last_minute + 1))
    final = md.meta["final_score"]
    assert pat["score"] == list(final)
    assert (pat["winner"] is None) == (final[0] == final[1])
    assert headlines(md, pat, "es")["neutral"] != headlines(md, pat)["neutral"]


def test_the_translation_check_keeps_names_and_numbers() -> None:
    names = ["Dunmoor", "Ashmere", "Ben D."]
    en = "Dunmoor are on top, and Ben D. is running the game."
    assert check_translation(en, "Dunmoor manda, y Ben D. dirige el partido.", names) == []
    assert any("Ben D." in p for p in check_translation(en, "Dunmoor manda, y Ben dirige el partido.", names))
    assert any("Ashmere" in p for p in check_translation(en, "Dunmoor manda ante Ashmere y Ben D. dirige el juego.", names))
    assert any("numbers" in p for p in check_translation(en, "Dunmoor manda con 2 goles, y Ben D. dirige el partido.", names))
    assert any("Spanish" in p for p in check_translation(en, en, names))
    assert any("Spanish" in p for p in check_translation(en, "Dunmoor are on top and Ben D. is running the juego.", names))


def test_azure_names_are_wrapped_so_the_service_leaves_them_alone() -> None:
    az = AzureBackend(key="k", region="r")
    wrapped = az._protect("Ben D. & Dunmoor <3", ["Ben D.", "Dunmoor"])
    assert wrapped.count('class="notranslate"') == 2 and "&amp;" in wrapped
    assert az._unprotect(wrapped) == "Ben D. & Dunmoor <3"


def test_a_failed_translation_goes_back_once_then_falls_back(tmp_path: Path) -> None:
    from swing.agents.translator import AgentBackend

    job = TranslateJob(
        [
            {"id": "a", "en": "Dunmoor are on top.", "fallback": "Dunmoor manda."},
            {"id": "b", "en": "Ashmere keep going.", "fallback": None},
        ],
        ["Dunmoor", "Ashmere"],
    )
    model = Says({"lines": {"a": "Dunmoor está arriba.", "b": "Ashmere keep going."}})
    done = asyncio.run(translate(AgentBackend(model), job))  # type: ignore[arg-type]
    assert done["a"] == ("Dunmoor está arriba.", "scripted")
    assert done["b"] == ("Ashmere keep going.", "english")
    assert model.calls == 2 and job.trace[-1]["rejected"] == 1


def test_enriching_keeps_the_cards_and_reads_their_facts_back(tmp_path: Path) -> None:
    md = _md(tmp_path)
    fresh = build(md)
    old = json.loads(json.dumps(fresh))
    for k in ("recap", "follow", "i18n"):
        old.pop(k)
    for c in old["cards"]:
        c.pop("detail"), c.pop("i18n")
    again = enriched(md, old)
    assert [c["text"] for c in again["cards"]] == [c["text"] for c in fresh["cards"]]
    # the Spanish read back from a card agrees with the Spanish written from its facts
    same = sum(a["i18n"]["es"]["text"] == b["i18n"]["es"]["text"] for a, b in zip(again["cards"], fresh["cards"], strict=True))
    assert same >= len(fresh["cards"]) - 1


def test_redirecting_applies_the_current_rules_to_an_old_bundle(tmp_path: Path, monkeypatch: Any) -> None:
    md = _md(tmp_path)
    with monkeypatch.context() as m:  # a bundle made under the old, looser rules
        m.setattr(director, "COOLDOWN", 5)
        m.setattr(director, "PER_HALF", 5)
        old = build(md)
    now = build(md)
    again = redirected(md, json.loads(json.dumps(old)))
    at = [c["at"] for c in again["cards"]]
    assert set(at) < {c["at"] for c in old["cards"]}  # cards only drop out
    assert sum(a <= 47 for a in at) <= director.PER_HALF and sum(a > 47 for a in at) <= director.PER_HALF
    calm = [(c, n) for c, n in zip(again["cards"][:-1], again["cards"][1:], strict=True) if n["kind"] in ("shift", "recovery")]
    assert all(n["at"] - c["at"] >= director.COOLDOWN for c, n in calm)
    assert {t["at"] for t in again["recap"]["turning_points"]} <= set(at)
    assert redirected(md, json.loads(json.dumps(now))) == now  # current bundles are left alone


def test_the_offline_agents_finish_a_bundle(tmp_path: Path) -> None:
    md = _md(tmp_path)
    b = build(md)
    finish([b], "offline")
    assert b["recap"]["agents"]["runner"] == "offline" and not b["recap"]["agents"]["fallback"]
    assert b["translator"]["backend"] == "offline"
    assert b["translator"]["lines"] == len(items(b))


def test_follow_tags_fire_once_per_threshold(tmp_path: Path) -> None:
    md = _md(tmp_path)
    b = build(md)
    for pid, f in b["follow"].items():
        kinds = [(x["kind"], x.get("value")) for x in f["moments"] if x["kind"] in THRESHOLDS]
        assert len(kinds) == len(set(kinds)), pid
        assert [x["m"] for x in f["moments"]] == sorted(x["m"] for x in f["moments"])
        assert len(f["involvement"]) == -(-(md.last_minute + 1) // 5)
    goals = sum(x["kind"] == "goal" for f in b["follow"].values() for x in f["moments"])
    assert goals == sum(md.meta["final_score"])


def test_translate_bundle_writes_spanish_and_skips_english_leftovers(tmp_path: Path) -> None:
    from swing.agents.translator import AgentBackend

    md = _md(tmp_path)
    b = build(md)
    asyncio.run(translate_bundle(AgentBackend(OfflineRunner()), b))
    for c in b["cards"]:
        for line in c["i18n"]["es"]["text"].values():
            assert not re.search(r"\b(the|are)\b", line)


def test_each_card_names_the_players_who_moved_its_swing(tmp_path: Path) -> None:
    md = _md(tmp_path)
    b = build(md)
    named = 0
    for c in b["cards"]:
        gainer = c["momentum"]["gainer"]
        for r in c["players"]:
            named += 1
            assert r["name"] == md.names[r["id"]]
            if r["role"] == "drove":  # the side that took over, doing more
                assert r["team"] == gainer and float(r["after"]) > float(r["before"])
            else:  # the side that lost it, doing less
                assert r["role"] == "faded" and r["team"] != gainer and float(r["after"]) < float(r["before"])
            assert r["label"] in b["i18n"]["es"]["labels"]
        assert len({r["id"] for r in c["players"]}) == len(c["players"])
    assert named
    parts = b["recap"]["parts"]
    assert sum(len(v) for v in parts.values()) == named
    for rows in parts.values():
        assert [x["at"] for x in rows] == sorted(x["at"] for x in rows)
    for c in b["cards"]:
        for r in c["players"]:
            assert any(x["at"] == c["at"] and x["role"] == r["role"] for x in parts[r["id"]])


def test_redirect_adds_the_players_to_older_bundles(tmp_path: Path) -> None:
    md = _md(tmp_path)
    b = build(md)
    for c in b["cards"]:
        del c["players"]
    del b["recap"]["parts"]
    again = redirected(md, json.loads(json.dumps(b)))
    fresh = {c["at"]: c["players"] for c in build(md)["cards"]}
    assert again["cards"] and all(c["players"] == fresh[c["at"]] for c in again["cards"])
    assert "parts" in again["recap"]
