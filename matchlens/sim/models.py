"""The probability models the simulator decides with.

Each model is a small closed-form function of position, pressure and player ratings, so
the numbers the simulator writes (xG, pass difficulty) can be explained and re-derived.
Positions are in the acting team's attacking frame.
"""

from __future__ import annotations

import math

from matchlens.contracts import PITCH_LENGTH_M, PITCH_WIDTH_M, WinProbability

GOAL_X = PITCH_LENGTH_M
GOAL_Y = PITCH_WIDTH_M / 2
GOAL_HALF_WIDTH = 7.32 / 2
BOX_X = PITCH_LENGTH_M - 16.5
BOX_Y = (PITCH_WIDTH_M / 2 - 20.16, PITCH_WIDTH_M / 2 + 20.16)
PENALTY_SPOT = (PITCH_LENGTH_M - 11.0, PITCH_WIDTH_M / 2)


def in_box(x: float, y: float) -> bool:
    """Inside the penalty area the team attacks."""
    return x >= BOX_X and BOX_Y[0] <= y <= BOX_Y[1]


def goal_distance(x: float, y: float) -> float:
    return math.hypot(GOAL_X - x, GOAL_Y - y)


def goal_angle(x: float, y: float) -> float:
    """Angle in radians the goal mouth subtends from ``(x, y)``."""
    dx = max(GOAL_X - x, 0.1)
    a1 = math.atan2(GOAL_Y + GOAL_HALF_WIDTH - y, dx)
    a2 = math.atan2(GOAL_Y - GOAL_HALF_WIDTH - y, dx)
    return abs(a1 - a2)


def expected_goals(
    x: float, y: float, pressure: float = 0.0, header: bool = False, blockers: int = 1
) -> float:
    """xG of a shot from ``(x, y)``: logistic in distance and goal-mouth angle.

    With one defender between shooter and goal and no pressure: about 0.65 from the
    six-yard line, 0.28 from the penalty spot, 0.13 from the edge of the box and 0.03
    from 25 m. Pressure lowers it, as does a header; a clear sight of goal (no outfield
    defender in the triangle to the posts) raises it, two or more defenders lower it.
    """
    d = goal_distance(x, y)
    logit = -0.6 - 0.13 * d + 1.7 * goal_angle(x, y)
    xg = 1.0 / (1.0 + math.exp(-logit))
    if header:
        xg *= 0.6
    xg *= 1.0 - 0.35 * pressure
    xg *= 1.45 if blockers == 0 else 0.8 if blockers >= 2 else 1.0
    return max(0.005, min(xg, 0.95))


def in_shot_triangle(shooter: tuple[float, float], p: tuple[float, float]) -> bool:
    """Whether ``p`` stands in the triangle from the shooter to the two posts (with a margin)."""
    sx, sy = shooter
    px, py = p
    if not sx < px <= GOAL_X:
        return False
    u = (px - sx) / max(GOAL_X - sx, 0.1)
    half = GOAL_HALF_WIDTH * u + 0.6
    centre = sy + (GOAL_Y - sy) * u
    return abs(py - centre) <= half


def threat(x: float, y: float) -> float:
    """Chance a possession at ``(x, y)`` ends in a goal soon. Rises steeply near goal."""
    d = math.hypot(GOAL_X - x, (GOAL_Y - y) * 1.35)
    return 0.004 + 0.0007 * x + 0.30 * math.exp(-d / 10.0)


def pressure_from_distance(d: float) -> float:
    """0 with the nearest opponent 6 m or more away, 1 when they are within a metre."""
    return max(0.0, min(1.0, (6.0 - d) / 5.0))


def pass_success(
    distance: float,
    lane_gap: float,
    receiver_gap: float,
    pressure: float,
    passing: int,
    lofted: bool,
) -> tuple[float, float]:
    """Probability a pass arrives, and its difficulty rating (0 easy to 1 very hard).

    ``lane_gap`` is the nearest opponent's distance from the pass line, ``receiver_gap``
    the nearest opponent's distance from the target. Difficulty uses the same factors
    without the passer's skill, so it describes the pass, not the passer.
    """
    base = 0.985 - 0.0042 * max(0.0, distance - 6.0) - 0.000035 * max(0.0, distance - 25.0) ** 2
    if lofted:
        base -= 0.06
    lane = 1.0 - 0.45 * math.exp(-lane_gap / 1.5)
    receiver = 1.0 - 0.22 * math.exp(-receiver_gap / 2.0)
    under_pressure = 1.0 - 0.10 * pressure
    raw = max(0.05, base * lane * receiver * under_pressure)
    difficulty = max(0.0, min(1.0, (1.0 - raw) * 1.6))
    skill = 0.94 + 0.12 * passing / 99
    return max(0.03, min(0.995, raw * skill)), difficulty


def ball_speed(distance: float, lofted: bool, shot: bool = False) -> float:
    """Initial ball speed in m/s for a pass or clearance of ``distance`` metres."""
    if lofted:
        return min(27.0, 11.0 + 0.30 * distance)
    return min(30.0, 8.5 + 0.38 * distance)


def flight_time(distance: float, speed: float, lofted: bool) -> float:
    """Seconds the ball takes to travel ``distance`` at initial ``speed``, with drag."""
    mean = speed * (0.62 if lofted else 0.74)
    return max(0.3, distance / mean)


def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def expected_goal_rates(
    home_rating: float, away_rating: float, home_advantage: float = 0.18
) -> tuple[float, float]:
    """Mean goals for each side from team ratings, fitted to simulator results."""
    edge = (home_rating - away_rating) * 0.042
    base = 1.30
    return base * math.exp(edge / 2 + home_advantage / 2), base * math.exp(
        -edge / 2 - home_advantage / 2
    )


def win_probability_from_rates(lam_home: float, lam_away: float) -> WinProbability:
    """Three-way probability from two independent Poisson goal counts."""
    home = draw = away = 0.0
    for i in range(11):
        pi = poisson_pmf(i, lam_home)
        for j in range(11):
            p = pi * poisson_pmf(j, lam_away)
            if i > j:
                home += p
            elif i == j:
                draw += p
            else:
                away += p
    total = home + draw + away
    return WinProbability(
        home=round(home / total, 3),
        draw=round(draw / total, 3),
        away=round(1.0 - round(home / total, 3) - round(draw / total, 3), 3),
    )


def pre_match_win_probability(home_rating: float, away_rating: float) -> WinProbability:
    """The synthetic pre-match win probability from the two club ratings."""
    return win_probability_from_rates(*expected_goal_rates(home_rating, away_rating))
