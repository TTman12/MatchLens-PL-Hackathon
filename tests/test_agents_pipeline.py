"""The agent pipeline end to end on the sample match, offline."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import jsonschema
import pytest

from matchlens.agents.audit import audit, audit_dir
from matchlens.agents.numbers import unsupported
from matchlens.agents.pipeline import main, run_match
from matchlens.agents.providers import ChaosProvider, OfflineProvider
from matchlens.contracts import EventType, MatchEvent
from matchlens.stats import load_match

from .agt_helpers import run
from .conftest import SAMPLE, SCHEMAS, load_json


def test_pipeline_finds_the_sample_moments() -> None:
    result = run()
    assert [str(m.type) for m in result.moments] == ["corner", "goal", "card"]


def test_both_engines_give_the_same_cues() -> None:
    af = run().cues.model_dump(mode="json")
    plain = run(engine="asyncio").cues.model_dump(mode="json")
    assert af == plain


def test_runs_are_deterministic() -> None:
    first = run().cues.model_dump(mode="json")
    again = asyncio.run(run_match(SAMPLE, OfflineProvider(), languages=["en", "es"]))
    assert again.cues.model_dump(mode="json") == first


def test_outputs_match_the_published_schemas(tmp_path: Path) -> None:
    run().write(tmp_path)
    cue_schema = load_json(SCHEMAS / "cue_track.schema.json")
    jsonschema.validate(load_json(tmp_path / "cues.json"), cue_schema)
    moment_schema = load_json(SCHEMAS / "moment.schema.json")
    for moment in load_json(tmp_path / "moments.json"):
        jsonschema.validate(moment, moment_schema)
    trace = load_json(tmp_path / "agent_trace.json")
    assert trace["provider"] == "offline"


def test_every_contributor_to_the_goal_gets_a_box() -> None:
    result = run()
    goal = next(m for m in result.moments if m.type == "goal")
    boxed = {
        c.player_id
        for c in result.cues.cues
        if c.moment_id == goal.moment_id and c.template == "fact_box" and c.layer == "player"
    }
    assert {"ash-09", "ash-08", "ash-06"} <= boxed


def test_goal_box_carries_contribution_and_win_probability() -> None:
    result = run()
    goal = next(m for m in result.moments if m.type == "goal")
    assert goal.swing > 0.2  # the goal swings Ashmere's win probability
    shares = [e for e in goal.evidence if e.source.startswith("attribution:")]
    assert {e.source.rsplit(":", 1)[1] for e in shares} >= {"ash-09", "ash-08", "ash-06"}
    assert abs(sum(e.numbers["share"] for e in shares) - 1.0) < 0.02
    club = next(
        c
        for c in result.cues.cues
        if c.moment_id == goal.moment_id and c.team_id == "ash" and c.lang == "en"
    )
    assert club.box is not None
    assert any(e.claim_type == "win_prob" for e in club.box.evidence)
    assert "44%" in club.box.body and "72%" in club.box.body


def test_suspension_card_gets_club_box_and_breaks_cooldown() -> None:
    result = run()
    card = next(m for m in result.moments if m.type == "card")
    club = [
        c
        for c in result.cues.cues
        if c.moment_id == card.moment_id and c.layer == "club" and c.lang == "en"
    ]
    assert [c.template for c in club] == ["fact_box"]
    assert club[0].box is not None and "ban" in (club[0].box.body + club[0].box.headline).lower()


def test_spanish_box_for_every_english_box() -> None:
    cues = run().cues.cues
    en = {(c.moment_id, c.layer, c.player_id, c.team_id) for c in cues if c.box and c.lang == "en"}
    es = {(c.moment_id, c.layer, c.player_id, c.team_id) for c in cues if c.box and c.lang == "es"}
    assert en == es
    sample = next(c for c in cues if c.lang == "es" and c.template == "fact_box")
    assert sample.box is not None and sample.box.headline


def test_no_number_on_screen_without_evidence() -> None:
    for cue in run().cues.cues:
        if cue.box is None:
            continue
        for text in (cue.box.headline, cue.box.body):
            assert not unsupported(text, cue.box.evidence, cue.lang), (cue.cue_id, text)


@pytest.mark.parametrize("chaos", [("kill:pundit",), ("kill:player", "kill:club", "kill:pundit")])
def test_killed_agents_fall_back_to_templates(chaos: tuple[str, ...]) -> None:
    result = run(*chaos)
    assert result.trace.degraded_agents()
    fallbacks = {v.status for m in result.moments for v in m.verdicts.values()}
    assert fallbacks == {"fallback"} if len(chaos) == 3 else "fallback" in fallbacks
    report = audit(SAMPLE, result.moments, result.cues)
    assert report.ok, report.problems
    # Killing a lens agent never costs the fan a box: the template takes over.
    assert sum(c.template == "fact_box" for c in result.cues.cues if c.lang == "en") == sum(
        c.template == "fact_box" for c in run().cues.cues if c.lang == "en"
    )


def test_killed_translator_leaves_boxes_in_english() -> None:
    result = run("kill:translator")
    assert not [c for c in result.cues.cues if c.lang == "es"]
    assert any(e.agent == "translator" and e.status == "skipped" for e in result.trace.events)
    assert result.cues.languages == ["en"]


def test_misquoting_agents_never_reach_the_screen() -> None:
    provider = ChaosProvider.from_rules(OfflineProvider(), ["misquote:*"])
    result = asyncio.run(run_match(SAMPLE, provider, languages=["en", "es"]))
    assert provider.corrupted
    caught = 0
    for m in result.moments:
        for key, verdict in m.verdicts.items():
            kind, _, subject = key.partition(":")
            group = getattr(m.drafts, kind)
            draft = group if kind == "pundit" else group.get(subject)
            if draft is not None and draft.agent in provider.corrupted:
                assert verdict.status != "approved", (m.moment_id, key)
                caught += 1
    assert caught == len(provider.corrupted)
    assert audit(SAMPLE, result.moments, result.cues).ok


def test_brief_at_period_end() -> None:
    match = load_match(SAMPLE)
    last = match.events[-1]
    end = MatchEvent(
        event_id="m017-e9999",
        match_id=match.match_id,
        t=last.t + 30.0,
        period=last.period,
        clock="90:00",
        type=EventType.PERIOD_END,
        qualifiers={},
    )
    match.events.append(end)
    result = asyncio.run(run_match(match, OfflineProvider(), languages=["en", "es"]))
    briefs = [c for c in result.cues.cues if c.template == "brief"]
    assert {c.lang for c in briefs} == {"en", "es"}
    en = next(c for c in briefs if c.lang == "en")
    assert en.box is not None and "1-0" in en.box.headline + en.box.body
    assert not unsupported(en.box.body, en.box.evidence, "en")


def test_cli_writes_outputs_and_audit_passes(tmp_path: Path) -> None:
    main([str(SAMPLE), "--out", str(tmp_path)])
    for name in ("moments.json", "cues.json", "agent_trace.json"):
        assert (tmp_path / name).exists()
    assert json.loads((tmp_path / "cues.json").read_text())["match_id"] == "m017"
    report = audit_dir(SAMPLE, tmp_path)
    assert report.ok, report.problems
    assert report.numbers_checked > 50
