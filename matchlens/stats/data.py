"""Load one match's files into memory, with the lookups every stat and agent needs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from matchlens.contracts import Club, Frame, League, MatchEvent, MatchMeta, Player, Season
from matchlens.contracts.season import PlayerSeasonStats, TableRow


@dataclass
class MatchData:
    """Everything known about one match: metadata, league, season, events and frames.

    The simulator and the sample match write the same files, so this loads either.
    """

    meta: MatchMeta
    league: League
    season: Season
    events: list[MatchEvent]
    frames: list[Frame] = field(repr=False)

    @property
    def match_id(self) -> str:
        return self.meta.match_id

    @property
    def home_id(self) -> str:
        return self.meta.home.team_id

    @property
    def away_id(self) -> str:
        return self.meta.away.team_id

    def is_home(self, team_id: str) -> bool:
        return team_id == self.home_id

    def opponent(self, team_id: str) -> str:
        return self.away_id if team_id == self.home_id else self.home_id

    @cached_property
    def clubs(self) -> dict[str, Club]:
        return {c.team_id: c for c in self.league.clubs}

    @cached_property
    def players(self) -> dict[str, Player]:
        return {p.player_id: p for c in self.league.clubs for p in c.squad}

    @cached_property
    def season_stats(self) -> dict[str, PlayerSeasonStats]:
        return {p.player_id: p for p in self.season.players}

    @cached_property
    def table(self) -> dict[str, TableRow]:
        return {r.team_id: r for r in self.season.table}

    @cached_property
    def events_by_id(self) -> dict[str, MatchEvent]:
        return {e.event_id: e for e in self.events}

    def team_of(self, player_id: str) -> str:
        return player_id.split("-", 1)[0]

    def short_name(self, player_id: str) -> str:
        player = self.players.get(player_id)
        return player.short_name if player else player_id

    def club_name(self, team_id: str) -> str:
        club = self.clubs.get(team_id)
        return club.short_name if club else team_id

    def period_start_t(self, period: int) -> float:
        for e in self.events:
            if e.type == "period_start" and e.period == period:
                return e.t
        return 0.0 if period == 1 else 45 * 60.0

    def regulation_end_t(self) -> float:
        """Match time at which 90 minutes are up, used by the win-probability model.

        Before period 2 has started its start is not known, so 45 minutes are assumed.
        """
        return self.period_start_t(2) + 45 * 60.0


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_match(directory: Path | str) -> MatchData:
    """Load ``match.json``, ``league.json``, ``season.json``, ``events.json`` and frames."""
    root = Path(directory)
    frames_path = root / "frames.jsonl"
    frames: list[Frame] = []
    if frames_path.exists():
        with frames_path.open(encoding="utf-8") as fh:
            frames = [Frame.model_validate_json(line) for line in fh if line.strip()]
    raw_events = _read_json(root / "events.json")
    assert isinstance(raw_events, list)
    return MatchData(
        meta=MatchMeta.model_validate(_read_json(root / "match.json")),
        league=League.model_validate(_read_json(root / "league.json")),
        season=Season.model_validate(_read_json(root / "season.json")),
        events=sorted(
            (MatchEvent.model_validate(e) for e in raw_events), key=lambda e: (e.t, e.event_id)
        ),
        frames=sorted(frames, key=lambda f: f.t),
    )
