"""In-play win probability, and the suspense and surprise measures built on it.

**Model.** Each side scores as a Poisson process for the rest of the match. The two
scoring rates are fitted once so that, at kick-off, the model reproduces the pre-match
win probability in ``match.json``. At any later moment the probability of each result
is the chance that the goals still to come turn the current score into a home win, a
draw or an away win. A red card cuts the side's rate by 30% and lifts the opponent's
by 20%.

**Swing** (the contract's measure) is the change in home win probability.

**Surprise and suspense** follow Ely, Frankel and Kamenica (2015), the measures that
track minute-by-minute football TV audiences (see the fan research):

- *surprise* is how far the result probabilities just moved: the total variation
  distance between the before and after vectors, so a goal that turns a likely draw
  into a likely away win counts fully whichever team you support;
- *suspense* is how far they *could* move next: the root-mean-square movement if a
  goal is scored in the next five minutes, weighted by how likely each goal is.

Both are 0 to 1. The Moment Detector uses them to score importance, and the Director
uses importance to spend the attention budget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from matchlens.contracts import EventType, Outcome, WinProbability

from .data import MatchData

EXPECTED_ADDED_TIME_S = 150.0
SUSPENSE_HORIZON_S = 300.0
RED_CARD_OWN_FACTOR = 0.7
RED_CARD_OPPONENT_FACTOR = 1.2
MAX_GOALS = 12


@dataclass(frozen=True)
class MatchState:
    """What the model needs to know at a point in the match."""

    t: float
    score_home: int = 0
    score_away: int = 0
    reds_home: int = 0
    reds_away: int = 0


def _poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


@lru_cache(maxsize=4096)
def outcome_probs(lam_home: float, lam_away: float, goal_diff: int) -> tuple[float, float, float]:
    """P(home win, draw, away win) given expected remaining goals and the current margin."""
    ph = [_poisson(k, lam_home) for k in range(MAX_GOALS + 1)]
    pa = [_poisson(k, lam_away) for k in range(MAX_GOALS + 1)]
    home = draw = away = 0.0
    for i, p_i in enumerate(ph):
        for j, p_j in enumerate(pa):
            margin = goal_diff + i - j
            p = p_i * p_j
            if margin > 0:
                home += p
            elif margin == 0:
                draw += p
            else:
                away += p
    total = home + draw + away
    return home / total, draw / total, away / total


def fit_rates(pre_match: WinProbability) -> tuple[float, float]:
    """Goals per 90 minutes for each side that reproduce the pre-match probabilities."""

    def error(lh: float, la: float) -> float:
        h, _, a = outcome_probs(lh, la, 0)
        return (h - pre_match.home) ** 2 + (a - pre_match.away) ** 2

    best = (1.4, 1.1)
    step = 0.4
    for _ in range(7):
        candidates = [
            (max(0.05, best[0] + dx * step), max(0.05, best[1] + dy * step))
            for dx in range(-3, 4)
            for dy in range(-3, 4)
        ]
        best = min(candidates, key=lambda c: error(*c))
        step /= 3
    return round(best[0], 4), round(best[1], 4)


class WinProbabilityModel:
    """Win probability for one match at any state. Deterministic."""

    def __init__(self, match: MatchData) -> None:
        self.match = match
        self.pre_match = match.meta.pre_match_win_prob
        self.rate_home, self.rate_away = fit_rates(self.pre_match)

    def remaining_s(self, t: float) -> float:
        end = self.match.regulation_end_t()
        if t <= end:
            return end - t + EXPECTED_ADDED_TIME_S
        return max(30.0, end + 2 * EXPECTED_ADDED_TIME_S - t)

    def _rates(self, state: MatchState, seconds: float) -> tuple[float, float]:
        frac = seconds / (90 * 60.0)
        lh, la = self.rate_home * frac, self.rate_away * frac
        lh *= RED_CARD_OWN_FACTOR**state.reds_home * RED_CARD_OPPONENT_FACTOR**state.reds_away
        la *= RED_CARD_OWN_FACTOR**state.reds_away * RED_CARD_OPPONENT_FACTOR**state.reds_home
        return lh, la

    def at(self, state: MatchState) -> WinProbability:
        """Win probability at ``state``, rounded to two places as shown on screen."""
        lh, la = self._rates(state, self.remaining_s(state.t))
        h, d, a = outcome_probs(round(lh, 4), round(la, 4), state.score_home - state.score_away)
        return rounded(h, d, a)

    def suspense(self, state: MatchState) -> float:
        """How far the result probabilities could move if a goal comes in the next 5 minutes."""
        now = self.at(state)
        lh, la = self._rates(state, min(SUSPENSE_HORIZON_S, self.remaining_s(state.t)))
        p_home_goal = 1 - math.exp(-lh)
        p_away_goal = 1 - math.exp(-la)
        after_home = self.at(_with_goal(state, home=True))
        after_away = self.at(_with_goal(state, home=False))
        variance = p_home_goal * distance(now, after_home) ** 2
        variance += p_away_goal * distance(now, after_away) ** 2
        return round(math.sqrt(variance), 3)

    def states(self) -> list[tuple[float, MatchState]]:
        """The match state after each event that changes it (goals and red cards)."""
        state = MatchState(t=0.0)
        out = [(0.0, state)]
        for e in self.match.events:
            if e.type is EventType.GOAL and e.qualifiers.score_home is not None:
                state = MatchState(
                    t=e.t,
                    score_home=e.qualifiers.score_home,
                    score_away=e.qualifiers.score_away or 0,
                    reds_home=state.reds_home,
                    reds_away=state.reds_away,
                )
                out.append((e.t, state))
            elif e.type is EventType.CARD and e.outcome in (Outcome.RED, Outcome.SECOND_YELLOW):
                home = e.team_id == self.match.home_id
                state = MatchState(
                    t=e.t,
                    score_home=state.score_home,
                    score_away=state.score_away,
                    reds_home=state.reds_home + (1 if home else 0),
                    reds_away=state.reds_away + (0 if home else 1),
                )
                out.append((e.t, state))
        return out

    def state_at(self, t: float, *, before: bool = False) -> MatchState:
        """State at match time ``t``. ``before=True`` excludes changes made exactly at ``t``."""
        current = MatchState(t=0.0)
        for when, state in self.states():
            if when < t or (when == t and not before):
                current = state
        return MatchState(
            t=t,
            score_home=current.score_home,
            score_away=current.score_away,
            reds_home=current.reds_home,
            reds_away=current.reds_away,
        )


def _with_goal(state: MatchState, *, home: bool) -> MatchState:
    return MatchState(
        t=state.t,
        score_home=state.score_home + (1 if home else 0),
        score_away=state.score_away + (0 if home else 1),
        reds_home=state.reds_home,
        reds_away=state.reds_away,
    )


def rounded(home: float, draw: float, away: float) -> WinProbability:
    """Round to two places, keeping the sum at exactly 1 by adjusting the largest share."""
    values = [round(home, 2), round(draw, 2), round(away, 2)]
    values[values.index(max(values))] += round(1 - sum(values), 2)
    return WinProbability(
        home=round(values[0], 2), draw=round(values[1], 2), away=round(values[2], 2)
    )


def distance(a: WinProbability, b: WinProbability) -> float:
    """Total variation distance between two result distributions, 0 to 1."""
    return 0.5 * (abs(a.home - b.home) + abs(a.draw - b.draw) + abs(a.away - b.away))


def swing(before: WinProbability, after: WinProbability) -> float:
    """The contract's swing: change in home win probability."""
    return round(after.home - before.home, 2)
