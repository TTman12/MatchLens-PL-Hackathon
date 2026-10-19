"""Deterministic stats: tracking, pass quality, xG, win probability, attribution, context."""

from __future__ import annotations

import pytest

from matchlens.contracts import WinProbability
from matchlens.stats.contribution import possession_value
from matchlens.stats.metrics import location_xg
from matchlens.stats.win_probability import MatchState, distance, fit_rates, outcome_probs, rounded

from .agt_helpers import stats


def test_tracking_matches_the_sample_scripts_own_measurements() -> None:
    run = stats().tracking.run("ash-09", 48.0, 59.6)
    assert run is not None
    assert (run.top_speed_kmh, run.distance_m) == (34.3, 77.5)
    assert 48.0 <= run.top_speed_t <= 59.6


def test_pass_quality_keeps_simulator_values_and_fills_gaps() -> None:
    m = stats()
    through = m.metrics.pass_quality(m.match.events_by_id["m017-e0024"])
    assert through is not None
    assert (through.distance_m, through.difficulty, through.line_breaking) == (25.3, 0.71, True)
    short = m.metrics.pass_quality(m.match.events_by_id["m017-e0019"])
    assert short is not None and 0 < short.difficulty < through.difficulty


def test_location_xg_falls_with_distance_and_for_headers() -> None:
    spot, edge, far = (
        location_xg((94, 34), None, 0),
        location_xg((88, 34), None, 0),
        location_xg((80, 34), None, 0),
    )
    assert spot > edge > far
    assert 0.15 < spot < 0.35
    assert location_xg((94, 34), "head", 0) < spot


def test_win_probability_reproduces_the_pre_match_numbers() -> None:
    model = stats().win_prob
    assert model.at(MatchState(t=0.0)) == model.pre_match


@pytest.mark.parametrize("pre", [(0.44, 0.28, 0.28), (0.2, 0.25, 0.55), (0.6, 0.25, 0.15)])
def test_fitted_rates_hit_any_reasonable_pre_match_line(pre: tuple[float, float, float]) -> None:
    h, d, a = pre
    lh, la = fit_rates(WinProbability(home=h, draw=d, away=a))
    ph, _, pa = outcome_probs(lh, la, 0)
    assert abs(ph - h) < 0.01 and abs(pa - a) < 0.01


def test_goals_and_red_cards_move_the_win_probability_the_right_way() -> None:
    model = stats().win_prob
    level = model.at(MatchState(t=600))
    assert model.at(MatchState(t=600, score_home=1)).home > level.home
    assert model.at(MatchState(t=600, reds_home=1)).home < level.home
    # Late leads are worth more than early ones.
    assert (
        model.at(MatchState(t=5000, score_home=1)).home
        > model.at(MatchState(t=600, score_home=1)).home
    )


def test_suspense_is_highest_when_a_goal_would_matter_most() -> None:
    model = stats().win_prob
    assert model.suspense(MatchState(t=5000)) > model.suspense(MatchState(t=5000, score_home=3))


def test_rounding_keeps_probabilities_summing_to_one() -> None:
    wp = rounded(0.333, 0.333, 0.334)
    assert abs(wp.home + wp.draw + wp.away - 1) < 1e-9
    assert distance(wp, wp) == 0


def test_attribution_credits_the_through_ball_and_the_finish() -> None:
    a = stats().attribution("m017-e0026")
    assert abs(sum(a.shares.values()) - 1) < 0.03
    ranked = [pid for pid, _ in a.ranked()]
    assert ranked[:2] == ["ash-09", "ash-08"]
    assert a.shares["ash-08"] > 0.2 > a.shares["ash-06"]
    assert a.touches["ash-06"] == 2


def test_possession_value_rises_towards_goal() -> None:
    assert possession_value((99, 34)) > possession_value((80, 34)) > possession_value((50, 34))
    assert possession_value((99, 34)) > possession_value((99, 5))


def test_momentum_stays_between_minus_one_and_one() -> None:
    for point in stats().momentum.series(step_s=30):
        assert -1 <= point.momentum <= 1


def test_live_table_and_discipline() -> None:
    c = stats().context
    assert c.live_position("ash", 60).position == 1  # type: ignore[union-attr]
    assert c.live_position("ash", 30).position == 2  # type: ignore[union-attr]
    d = c.discipline_after("m017-e0033")
    assert d.banned and d.yellows_toward_ban == 5
    assert d.banned_for is not None and d.banned_for.match_id == "m019"
    assert c.season_goals("ash-09", 60) == 7


def test_player_match_stats() -> None:
    s = stats().player_match_stats("ash-08")
    assert s.passes == 3 and s.pass_accuracy == 1.0
    assert s.top_speed_kmh is not None and s.top_speed_kmh > 25
