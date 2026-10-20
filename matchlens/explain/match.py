"""A match as the agents see it: the public tables only (docs/data-format.md), never the truth.

Everything here works on any match folder in the public format. Windows are half-open minute
ranges [lo, hi) on the continuous match minute `m`.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..data.aggregate import aggregate

Row = dict[str, float]

KEY_EVENTS = ("goal", "red_card", "substitution", "half_time")


@dataclass
class KeyEvent:
    """An event that can anchor an event-mode card."""

    kind: str  # goal | red_card | substitution | half_time
    m: int
    clock: str
    team_id: str | None
    event_id: str | None = None
    player_id: str | None = None
    player_off_id: str | None = None


@dataclass
class MatchData:
    meta: dict[str, Any]
    events: list[dict[str, Any]]
    team: dict[str, list[Row]]  # team_id -> one row per minute, index = m
    player: dict[str, dict[int, Row]]  # player_id -> m -> row
    player_team: dict[str, str]
    names: dict[str, str]
    roles: dict[str, str]
    key_events: list[KeyEvent] = field(default_factory=list)
    clocks: list[str] = field(default_factory=list)  # broadcast minute for each m, e.g. "45+2"

    @property
    def teams(self) -> list[str]:
        return [t["team_id"] for t in self.meta["teams"]]

    @property
    def last_minute(self) -> int:
        return len(self.team[self.teams[0]]) - 1

    def opp(self, team: str) -> str:
        a, b = self.teams
        return b if team == a else a

    def short(self, team: str) -> str:
        return str(next(t.get("short_name") or t["name"] for t in self.meta["teams"] if t["team_id"] == team))

    def total(self, team: str, lo: int, hi: int, k: str) -> float:
        rows = self.team[team]
        return sum(rows[m].get(k, 0.0) for m in range(max(lo, 0), min(hi, len(rows))))

    def player_total(self, pid: str, lo: int, hi: int, k: str) -> float:
        rows = self.player.get(pid, {})
        return sum(rows[m].get(k, 0.0) for m in range(max(lo, 0), hi) if m in rows)

    def player_minutes(self, pid: str, lo: int, hi: int) -> int:
        rows = self.player.get(pid, {})
        return sum(1 for m in range(max(lo, 0), hi) if m in rows)

    def score_at(self, m: int) -> dict[str, int]:
        """Score at the start of minute m."""
        out = {}
        for t in self.teams:
            rows = self.team[t]
            out[t] = int(rows[min(m, len(rows) - 1)]["goals_for_before"])
        return out

    def clock_of(self, m: int) -> str:
        """The broadcast minute during match minute m (m = 0 is 1')."""
        if 0 <= m < len(self.clocks) and self.clocks[m]:
            c = self.clocks[m]
            base, _, extra = c.partition("+")
            return f"{base}+{int(extra) + 1}'" if extra else f"{int(base) + 1}'"
        return f"{m + 1}'"

    def until(self, now: int) -> MatchData:
        """The match as it stood at the start of minute `now` (for live use and leak tests)."""
        events = [e for e in self.events if e["m"] < now]
        return MatchData(
            self.meta,
            events,
            {t: rows[:now] for t, rows in self.team.items()},
            {p: {m: r for m, r in rows.items() if m < now} for p, rows in self.player.items()},
            self.player_team,
            self.names,
            self.roles,
            [k for k in self.key_events if k.m < now],
            self.clocks[:now],
        )


def _num(rows: list[dict[str, Any]], skip: tuple[str, ...]) -> list[Row]:
    return [{k: float(v) for k, v in r.items() if k not in skip and v not in ("", None)} for r in rows]


def key_events(events: list[dict[str, Any]]) -> list[KeyEvent]:
    out: list[KeyEvent] = []
    seen_second_half = False
    for e in events:
        mm, _, _ = str(e["clock"]).partition(":")
        base, _, extra = mm.partition("+")
        clock = f"{base}+{int(extra) + 1}'" if extra else f"{int(base) + 1}'"
        if e["type"] == "shot" and e["outcome"] == "goal":
            out.append(KeyEvent("goal", e["m"], clock, e["team_id"], e["id"], e.get("player_id")))
        elif e["type"] == "foul" and e.get("card") in ("red", "second_yellow"):
            out.append(KeyEvent("red_card", e["m"], clock, e["team_id"], e["id"], e.get("player_id")))
        elif e["type"] == "substitution":
            out.append(KeyEvent("substitution", e["m"], clock, e["team_id"], e["id"], e.get("player_id"), e.get("player_off_id")))
        elif e["period"] == 2 and not seen_second_half:
            seen_second_half = True
            out.append(KeyEvent("half_time", e["m"], "HT", None, None))
    return out


def from_parts(meta: dict[str, Any], events: list[dict[str, Any]], physical: list[dict[str, Any]] | None = None) -> MatchData:
    team_rows, player_rows = aggregate(meta, events, physical)
    teams = [t["team_id"] for t in meta["teams"]]
    team: dict[str, list[Row]] = {t: [] for t in teams}
    for r, raw in zip(_num(team_rows, ("team_id", "clock_minute")), team_rows, strict=True):
        team[raw["team_id"]].append(r)
    player: dict[str, dict[int, Row]] = {}
    for r, raw in zip(_num(player_rows, ("team_id", "player_id")), player_rows, strict=True):
        player.setdefault(raw["player_id"], {})[int(r["m"])] = r
    players = [(t["team_id"], p) for t in meta["teams"] for p in t["players"]]
    return MatchData(
        meta=meta,
        events=events,
        team=team,
        player=player,
        player_team={p["player_id"]: t for t, p in players},
        names={p["player_id"]: p.get("short_name") or p["name"] for _, p in players},
        roles={p["player_id"]: p.get("role", "") for _, p in players},
        key_events=key_events(events),
        clocks=[str(r["clock_minute"]) for r in team_rows if r["team_id"] == teams[0]],
    )


def load(folder: Path) -> MatchData:
    """Read a match folder. Derived tables are rebuilt from the events so any supplier's folder works."""
    meta = json.loads((folder / "match.json").read_text())
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines() if line.strip()]
    physical: list[dict[str, Any]] = []
    phys = folder / "physical.csv"
    if phys.exists() and phys.read_text().strip():
        with phys.open(newline="") as f:
            physical = list(csv.DictReader(f))
    return from_parts(meta, events, physical)
