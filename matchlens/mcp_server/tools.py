"""Match-State tools: the lookups the MCP server exposes and the agents call in-process.

Every tool returns plain JSON. Tools that state facts also return them as ``facts``:
``{claim_type, value, source, numbers}`` records in the same shape as a moment's
evidence items, so an agent can add a looked-up fact to the moment and cite it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from matchlens.contracts import ClaimType, Moment
from matchlens.stats import StatsEngine, load_match
from matchlens.stats.win_probability import MatchState

Fact = dict[str, Any]


def fact(claim_type: ClaimType, value: str, source: str, numbers: dict[str, float | None]) -> Fact:
    return {
        "claim_type": str(claim_type),
        "value": value,
        "source": source,
        "numbers": {k: float(v) for k, v in numbers.items() if v is not None},
    }


class MatchStateStore:
    """One match's stats engine plus the moments detected so far."""

    def __init__(self, stats: StatsEngine, moments: list[Moment] | None = None) -> None:
        self.stats = stats
        self.match = stats.match
        self.moments: dict[str, Moment] = {m.moment_id: m for m in moments or []}

    @classmethod
    def from_dir(
        cls, match_dir: Path | str, moments_path: Path | str | None = None
    ) -> MatchStateStore:
        stats = StatsEngine(load_match(match_dir))
        moments: list[Moment] = []
        if moments_path and Path(moments_path).exists():
            raw = json.loads(Path(moments_path).read_text(encoding="utf-8"))
            moments = [Moment.model_validate(m) for m in raw]
        return cls(stats, moments)

    def add_moment(self, moment: Moment) -> None:
        self.moments[moment.moment_id] = moment

    # -- tools ----------------------------------------------------------------------------

    def get_match(self) -> dict[str, Any]:
        """Teams, stadium, stakes and pre-match win probability for the streamed match."""
        meta = self.match.meta
        return {
            "match_id": meta.match_id,
            "matchday": meta.matchday,
            "home": {"team_id": meta.home.team_id, "name": self.match.club_name(meta.home.team_id)},
            "away": {"team_id": meta.away.team_id, "name": self.match.club_name(meta.away.team_id)},
            "stadium": meta.stadium,
            "stakes": meta.stakes.model_dump(),
            "pre_match_win_prob": meta.pre_match_win_prob.model_dump(),
        }

    def list_moments(self) -> list[dict[str, Any]]:
        """Every detected moment so far: id, type, time, importance and swing."""
        return [
            {
                "moment_id": m.moment_id,
                "type": str(m.type),
                "t_peak": m.t_peak,
                "importance": m.importance,
                "swing": m.swing,
                "status": str(m.status),
            }
            for m in sorted(self.moments.values(), key=lambda m: m.t_peak)
        ]

    def get_moment(self, moment_id: str) -> dict[str, Any]:
        """The full moment record: involved players, evidence, drafts, verdicts, decision."""
        moment = self.moments.get(moment_id)
        if moment is None:
            raise KeyError(f"no moment {moment_id}")
        return moment.model_dump(mode="json")

    def get_player_match_stats(self, player_id: str, t: float | None = None) -> dict[str, Any]:
        """A player's match so far: touches, passing, shots, xG, top speed and distance."""
        if player_id not in self.match.players:
            raise KeyError(f"no player {player_id}")
        s = self.stats.player_match_stats(player_id, t)
        name = self.match.short_name(player_id)
        until = "so far" if t is None else f"to {t:.0f}s"
        facts = [
            fact(
                ClaimType.STAT,
                f"{name}: {s.passes_complete} of {s.passes} passes complete {until}",
                f"match:{player_id}:passes",
                {
                    "passes": s.passes,
                    "passes_complete": s.passes_complete,
                    "pass_accuracy": s.pass_accuracy,
                },
            )
        ]
        if s.top_speed_kmh is not None:
            facts.append(
                fact(
                    ClaimType.STAT,
                    f"{name}: top speed {s.top_speed_kmh} km/h {until}",
                    f"match:{player_id}:top_speed",
                    {"top_speed_kmh": s.top_speed_kmh},
                )
            )
        return {"stats": s.as_dict(), "facts": facts}

    def get_season_stats(self, player_id: str) -> dict[str, Any]:
        """A player's league season before this match: goals, assists, cards, top speed."""
        s = self.match.season_stats.get(player_id)
        if s is None:
            raise KeyError(f"no season stats for {player_id}")
        name = self.match.short_name(player_id)
        facts = [
            fact(
                ClaimType.SEASON,
                f"{name}: {s.goals} league goals and {s.assists} assists before today",
                f"season:{player_id}:goals",
                {"goals": s.goals, "assists": s.assists, "appearances": s.appearances},
            ),
            fact(
                ClaimType.DISCIPLINE,
                f"{name}: {s.yellow_cards} yellow cards toward a ban",
                f"season:{player_id}:yellow_cards",
                {"yellows": s.yellow_cards},
            ),
        ]
        if s.top_speed_kmh is not None:
            facts.append(
                fact(
                    ClaimType.SEASON,
                    f"{name}'s season top speed {s.top_speed_kmh} km/h",
                    f"season:{player_id}:top_speed",
                    {"top_speed_kmh": s.top_speed_kmh},
                )
            )
        return {"stats": s.model_dump(mode="json"), "facts": facts}

    def get_table(self, live_at_t: float | None = None) -> dict[str, Any]:
        """The league table before kick-off, or the live table at match time ``live_at_t``."""
        if live_at_t is None:
            rows = [r.model_dump(mode="json") for r in self.match.season.table]
            facts = [
                fact(
                    ClaimType.TABLE,
                    f"{self.match.club_name(r.team_id)} "
                    f"{r.position} on {r.points} points before today",
                    f"table:{r.team_id}",
                    {"position": r.position, "points": r.points},
                )
                for r in self.match.season.table
            ]
            return {"table": rows, "facts": facts}
        live = self.stats.context.live_table(live_at_t)
        facts = [
            fact(
                ClaimType.TABLE,
                f"{self.match.club_name(r.team_id)} {r.position} on the "
                f"live table, {r.points} points",
                f"table:live:{r.team_id}",
                {"position": r.position, "points": r.points},
            )
            for r in live
        ]
        return {"table": [r.__dict__ for r in live], "facts": facts}

    def get_fixtures(self, team_id: str) -> dict[str, Any]:
        """A club's played and upcoming league fixtures, and its next match."""
        fixtures = [
            f.model_dump(mode="json")
            for f in self.match.season.fixtures
            if team_id in (f.home_id, f.away_id)
        ]
        nxt = self.stats.context.next_fixture(team_id)
        facts = []
        if nxt is not None:
            opp = nxt.away_id if nxt.home_id == team_id else nxt.home_id
            venue = "home to" if nxt.home_id == team_id else "away at"
            facts.append(
                fact(
                    ClaimType.FIXTURE,
                    f"Next match: {venue} {self.match.club_name(opp)}, matchday {nxt.matchday}",
                    f"fixture:{nxt.match_id}",
                    {"matchday": nxt.matchday},
                )
            )
        return {
            "fixtures": fixtures,
            "next": nxt.model_dump(mode="json") if nxt else None,
            "facts": facts,
        }

    def win_probability(
        self, t: float, score_home: int | None = None, score_away: int | None = None
    ) -> dict[str, Any]:
        """Win probability and suspense at match time ``t``, at the real or a what-if score."""
        state = self.stats.win_prob.state_at(t)
        if score_home is not None or score_away is not None:
            state = MatchState(
                t=t,
                score_home=score_home if score_home is not None else state.score_home,
                score_away=score_away if score_away is not None else state.score_away,
                reds_home=state.reds_home,
                reds_away=state.reds_away,
            )
        wp = self.stats.win_prob.at(state)
        home, away = (
            self.match.club_name(self.match.home_id),
            self.match.club_name(self.match.away_id),
        )
        return {
            "state": state.__dict__,
            "win_prob": wp.model_dump(),
            "suspense": self.stats.win_prob.suspense(state),
            "facts": [
                fact(
                    ClaimType.WIN_PROB,
                    f"At {state.score_home}-{state.score_away}: {home} "
                    f"{round(wp.home * 100)}%, {away} {round(wp.away * 100)}%",
                    f"winprob:{self.match.match_id}:{t:g}",
                    {
                        "home": wp.home,
                        "draw": wp.draw,
                        "away": wp.away,
                        "score_home": state.score_home,
                        "score_away": state.score_away,
                    },
                )
            ],
        }

    def get_contribution(self, shot_event_id: str) -> dict[str, Any]:
        """Contribution shares for the move that ended in a shot, with each action's value."""
        a = self.stats.attribution(shot_event_id)
        return {
            "shot_event_id": a.shot_event_id,
            "shares": a.shares,
            "touches": a.touches,
            "chain": [c.__dict__ | {"type": str(c.type)} for c in a.chain],
            "facts": [
                fact(
                    ClaimType.STAT,
                    f"{self.match.short_name(pid)}: {round(s * 100)}% of the move's value",
                    f"attribution:{shot_event_id}:{pid}",
                    {"share": s, "touches": a.touches.get(pid, 0)},
                )
                for pid, s in a.ranked()
            ],
        }

    def get_momentum(self, t: float) -> dict[str, Any]:
        """Threat points for each side over the five minutes to ``t``, and momentum (-1 to 1)."""
        p = self.stats.momentum.at(t)
        return {
            "momentum": p.__dict__,
            "facts": [
                fact(
                    ClaimType.STAT,
                    f"Threat over five minutes: home {p.home_threat}, away {p.away_threat}",
                    f"momentum:{self.match.match_id}:{t:g}",
                    {
                        "home_threat": p.home_threat,
                        "away_threat": p.away_threat,
                        "momentum": p.momentum,
                    },
                )
            ],
        }


TOOL_NAMES = (
    "get_match",
    "list_moments",
    "get_moment",
    "get_player_match_stats",
    "get_season_stats",
    "get_table",
    "get_fixtures",
    "win_probability",
    "get_contribution",
    "get_momentum",
)
