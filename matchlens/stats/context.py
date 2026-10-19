"""Season context at a point in the match: table, live table, fixtures, discipline, milestones.

Everything here is computed from ``season.json`` plus the events of the streamed match
up to time ``t``, so it is what a broadcaster's stats desk would know at that moment.
"""

from __future__ import annotations

from dataclasses import dataclass

from matchlens.contracts import EventType, Outcome
from matchlens.contracts.season import Fixture, TableRow

from .data import MatchData


@dataclass(frozen=True)
class LiveRow:
    team_id: str
    position: int
    points: int
    goal_difference: int
    goals_for: int


@dataclass(frozen=True)
class Discipline:
    """A player's yellow-card position after a card in this match."""

    player_id: str
    yellows_toward_ban: int
    threshold: int
    banned: bool
    reason: str
    banned_for: Fixture | None


class SeasonContext:
    def __init__(self, match: MatchData) -> None:
        self.match = match
        self.season = match.season

    # -- score and goals in the streamed match -------------------------------------------

    def score_at(self, t: float) -> tuple[int, int]:
        home = away = 0
        for e in self.match.events:
            if e.t > t:
                break
            if e.type is EventType.GOAL and e.qualifiers.score_home is not None:
                home, away = e.qualifiers.score_home, e.qualifiers.score_away or 0
        return home, away

    def match_goals(self, player_id: str, t: float) -> int:
        return sum(
            1
            for e in self.match.events
            if e.type is EventType.GOAL
            and e.player_id == player_id
            and e.t <= t
            and not e.qualifiers.own_goal
        )

    def season_goals(self, player_id: str, t: float) -> int:
        """League goals this season including the streamed match up to ``t``."""
        stats = self.match.season_stats.get(player_id)
        return (stats.goals if stats else 0) + self.match_goals(player_id, t)

    def matchdays_since_goal(self, player_id: str) -> int | None:
        stats = self.match.season_stats.get(player_id)
        if stats is None or stats.last_goal_matchday is None:
            return None
        return self.match.meta.matchday - stats.last_goal_matchday

    # -- table ----------------------------------------------------------------------------

    def table_row(self, team_id: str) -> TableRow | None:
        return self.match.table.get(team_id)

    def live_table(self, t: float) -> list[LiveRow]:
        """The table if the streamed match ended with the score at ``t``."""
        home_goals, away_goals = self.score_at(t)
        rules = self.season.rules
        rows: list[LiveRow] = []
        for row in self.season.table:
            points, gf, ga = row.points, row.goals_for, row.goals_against
            if row.team_id in (self.match.home_id, self.match.away_id):
                ours, theirs = (
                    (home_goals, away_goals)
                    if row.team_id == self.match.home_id
                    else (away_goals, home_goals)
                )
                gf, ga = gf + ours, ga + theirs
                if ours > theirs:
                    points += rules.points_for_win
                elif ours == theirs:
                    points += rules.points_for_draw
            rows.append(LiveRow(row.team_id, 0, points, gf - ga, gf))
        rows.sort(key=lambda r: (-r.points, -r.goal_difference, -r.goals_for, r.team_id))
        return [
            LiveRow(r.team_id, i + 1, r.points, r.goal_difference, r.goals_for)
            for i, r in enumerate(rows)
        ]

    def live_position(self, team_id: str, t: float) -> LiveRow | None:
        return next((r for r in self.live_table(t) if r.team_id == team_id), None)

    # -- fixtures -------------------------------------------------------------------------

    def next_fixture(self, team_id: str) -> Fixture | None:
        """The team's next league match after this one."""
        upcoming = [
            f
            for f in self.season.fixtures
            if f.status == "scheduled"
            and f.matchday > self.match.meta.matchday
            and team_id in (f.home_id, f.away_id)
        ]
        return min(upcoming, key=lambda f: (f.matchday, f.match_id), default=None)

    # -- discipline -----------------------------------------------------------------------

    def discipline_after(self, card_event_id: str) -> Discipline:
        """Where a booked player stands after the card, and whether it brings a ban."""
        card = self.match.events_by_id[card_event_id]
        assert card.player_id is not None and card.team_id is not None
        stats = self.match.season_stats.get(card.player_id)
        before = stats.yellow_cards if stats else 0
        in_match = sum(
            1
            for e in self.match.events
            if e.type is EventType.CARD
            and e.player_id == card.player_id
            and e.outcome is Outcome.YELLOW
            and e.t <= card.t
        )
        threshold = self.season.rules.yellow_card_ban_threshold
        yellows = before + in_match
        if card.outcome in (Outcome.RED, Outcome.SECOND_YELLOW):
            banned, reason = True, "sent_off"
        else:
            banned, reason = yellows >= threshold, "yellow_threshold"
        return Discipline(
            player_id=card.player_id,
            yellows_toward_ban=yellows,
            threshold=threshold,
            banned=banned,
            reason=reason if banned else "none",
            banned_for=self.next_fixture(card.team_id) if banned else None,
        )
