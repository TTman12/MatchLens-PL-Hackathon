"""Unit tests for the rules the contracts enforce beyond plain types."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from matchlens.contracts import Cue, Draft, MatchEvent, Moment, WinProbability, format_clock
from matchlens.contracts.export import main as export_schemas
from matchlens.contracts.pitch import attacking_direction, to_attacking, to_pitch


def event(**overrides: Any) -> dict[str, Any]:
    base = {
        "event_id": "m042-e0317",
        "match_id": "m042",
        "t": 2714.3,
        "period": 1,
        "clock": "45+0:14",
        "type": "pass",
        "team_id": "ash",
        "player_id": "ash-08",
        "start": [61.2, 30.5],
        "end": [84.0, 22.1],
        "outcome": "complete",
        "receiver_id": "ash-09",
    }
    return base | overrides


def moment(**overrides: Any) -> dict[str, Any]:
    even = {"home": 0.4, "draw": 0.3, "away": 0.3}
    base = {
        "moment_id": "m042-mo07",
        "match_id": "m042",
        "type": "goal",
        "period": 1,
        "t_start": 2701.0,
        "t_peak": 2716.8,
        "t_end": 2719.0,
        "replay_window": [2701.0, 2719.0],
        "importance": 0.9,
        "win_prob_before": even,
        "win_prob_after": even,
        "swing": 0.0,
        "evidence": [{"id": "ev1", "claim_type": "stat", "value": "x", "source": "m042-e0317"}],
    }
    return base | overrides


class TestClockAndPitch:
    @pytest.mark.parametrize(
        ("t", "period", "start", "clock"),
        [
            (0.0, 1, 0.0, "0:00"),
            (754.9, 1, 0.0, "12:34"),
            (2714.3, 1, 0.0, "45+0:14"),
            (2834.0, 1, 0.0, "45+2:14"),
            (2880.0, 2, 2880.0, "45:00"),
            (2880.0 + 2700 + 61, 2, 2880.0, "90+1:01"),
        ],
    )
    def test_format_clock(self, t: float, period: int, start: float, clock: str) -> None:
        assert format_clock(t, period, start) == clock

    def test_teams_swap_ends_at_half_time(self) -> None:
        assert attacking_direction("+x", is_home=True, period=1) == "+x"
        assert attacking_direction("+x", is_home=False, period=1) == "-x"
        assert attacking_direction("+x", is_home=True, period=2) == "-x"
        assert attacking_direction("+x", is_home=False, period=2) == "+x"

    def test_frames_round_trip(self) -> None:
        point = (12.0, 50.0)
        assert to_pitch(point, "+x") == point
        assert to_pitch(point, "-x") == (93.0, 18.0)
        assert to_attacking(to_pitch(point, "-x"), "-x") == point


class TestEvents:
    def test_plan_example_is_valid(self) -> None:
        MatchEvent.model_validate(event(qualifiers={"distance_m": 24.3, "difficulty": 0.71}))

    def test_outcome_must_suit_the_type(self) -> None:
        with pytest.raises(ValidationError, match="not valid for a pass"):
            MatchEvent.model_validate(event(outcome="goal"))

    def test_team_events_need_a_team(self) -> None:
        with pytest.raises(ValidationError, match="need a team_id"):
            MatchEvent.model_validate(event(team_id=None))

    def test_event_id_belongs_to_match(self) -> None:
        with pytest.raises(ValidationError, match="must start with match_id"):
            MatchEvent.model_validate(event(match_id="m043"))

    def test_unknown_fields_are_rejected_but_qualifiers_are_open(self) -> None:
        with pytest.raises(ValidationError):
            MatchEvent.model_validate(event(colour="red"))
        parsed = MatchEvent.model_validate(event(qualifiers={"new_metric": 3}))
        assert parsed.qualifiers.model_extra == {"new_metric": 3}

    def test_bad_ids_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MatchEvent.model_validate(event(player_id="Ash 8"))


class TestMoment:
    def test_win_probabilities_sum_to_one(self) -> None:
        with pytest.raises(ValidationError, match="sum to 1"):
            WinProbability(home=0.5, draw=0.5, away=0.5)

    def test_drafts_must_cite_known_evidence(self) -> None:
        draft = {"lens": "pundit", "headline": "h", "evidence_ids": ["ev9"]}
        with pytest.raises(ValidationError, match="unknown evidence"):
            Moment.model_validate(moment(drafts={"pundit": draft}))

    def test_times_must_be_ordered(self) -> None:
        with pytest.raises(ValidationError, match="t_start <= t_peak"):
            Moment.model_validate(moment(t_peak=2800.0))

    def test_no_box_draft_needs_no_text(self) -> None:
        Draft(lens="club", subject_id="brk", kind="no_box")
        with pytest.raises(ValidationError, match="needs a headline"):
            Draft(lens="club", subject_id="brk")


class TestCue:
    def cue(self, **overrides: Any) -> dict[str, Any]:
        base = {
            "cue_id": "m042-c019",
            "match_id": "m042",
            "t_show": 2735.0,
            "duration": 8,
            "layer": "player",
            "template": "fact_box",
            "player_id": "ash-09",
            "box": {"headline": "Varrow: 33.4 km/h"},
        }
        return base | overrides

    def test_valid(self) -> None:
        Cue.model_validate(self.cue())

    def test_player_layer_needs_player(self) -> None:
        with pytest.raises(ValidationError, match="need a player_id"):
            Cue.model_validate(self.cue(player_id=None))

    def test_fact_box_needs_box(self) -> None:
        with pytest.raises(ValidationError, match="need a box"):
            Cue.model_validate(self.cue(box=None))

    def test_replay_needs_window(self) -> None:
        with pytest.raises(ValidationError, match="replay window"):
            Cue.model_validate(self.cue(template="replay", camera={"shot": "spidercam_goal"}))


def test_committed_schemas_are_current() -> None:
    assert export_schemas(["--check"]) == 0, "run `matchlens-schemas` and commit the result"
