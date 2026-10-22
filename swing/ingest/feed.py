"""The feed adapter: a live match arriving as per-minute tables, turned into what the agents read.

A provider sends, once a minute:

- one row per club with that minute's club stats,
- one row per player on the pitch with that minute's player stats, and
- the minute's key events: kick-offs, goals, cards and substitutions.

Before kick-off it sends the line-ups. Its column names are its own: a small mapping file
(mappings/example-provider.json) says which of its columns is which of ours. Scores, players on
the pitch and half-time are worked out from the events, so the feed needn't send them.

`LiveMatch.add` takes one minute at a time; `md` is the match as it stands, in the same shape
`explain.match.load` gives for a recorded match (docs/live-feed.md).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..data.aggregate import PLAYER_COLUMNS, TEAM_COLUMNS
from ..explain.match import MatchData, Row, key_events

MAPPINGS = Path(__file__).parent / "mappings"
DEFAULT_MAPPING = MAPPINGS / "example-provider.json"
EVENT_KINDS = ("period_start", "goal", "yellow_card", "second_yellow", "red_card", "substitution")
DERIVED = ("goals_for_before", "goals_against_before", "players_on")  # worked out from the events if not sent

Mapping = dict[str, Any]


def load_mapping(path: Path | None = None) -> Mapping:
    mapping: Mapping = json.loads((path or DEFAULT_MAPPING).read_text())
    for part in ("team", "player", "events", "kinds", "lineup"):
        mapping.setdefault(part, {})
    return mapping


def _rename(row: dict[str, Any], cols: dict[str, str]) -> dict[str, Any]:
    """A provider's row in our names. Columns the mapping doesn't name are dropped."""
    return {ours: row[theirs] for theirs, ours in cols.items() if theirs in row}


@dataclass
class Minute:
    """One minute of the feed, already in our names."""

    m: int
    team: dict[str, dict[str, Any]]  # team_id -> row
    players: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


def to_minute(
    m: int, team_rows: list[dict[str, Any]], player_rows: list[dict[str, Any]], events: list[dict[str, Any]], mapping: Mapping
) -> Minute:
    """One minute of a provider's rows, renamed."""
    team = [_rename(r, mapping["team"]) for r in team_rows]
    evs = []
    for e in events:
        ev = _rename(e, mapping["events"])
        kind = mapping["kinds"].get(ev.get("kind"), ev.get("kind"))
        if kind not in EVENT_KINDS:
            continue  # a kind we don't use (a shot, a corner...): the tables already count it
        evs.append({**ev, "kind": kind})
    return Minute(m, {str(r["team_id"]): r for r in team}, [_rename(r, mapping["player"]) for r in player_rows], evs)


def lineup_meta(lineup: dict[str, Any], mapping: Mapping) -> dict[str, Any]:
    """Match metadata from the provider's line-ups: who plays for whom, in what role, who starts."""
    meta = {k: v for k, v in lineup.items() if k != "teams"}
    meta["teams"] = []
    for t in lineup["teams"]:
        players = []
        for p in t["players"]:
            q = _rename(p, mapping["lineup"]) if mapping["lineup"] else dict(p)
            q["starter"] = q.get("starter") in (True, "true", "True", "1", 1, "yes")
            players.append(q)
        meta["teams"].append({**{k: v for k, v in t.items() if k != "players"}, "players": players})
    return meta


def _event(e: dict[str, Any], m: int) -> dict[str, Any]:
    """A feed event as a public-format event (docs/data-format.md), so the usual key-event rules apply."""
    kind = e["kind"]
    base = {
        "id": e.get("id"),
        "m": m,
        "period": int(e["period"]),
        "clock": str(e.get("clock") or ""),
        "team_id": e.get("team_id"),
        "player_id": e.get("player_id") or None,
        "outcome": "",
    }
    if kind == "goal":
        return {**base, "type": "shot", "subtype": "open_play", "outcome": "goal"}
    if kind in ("yellow_card", "second_yellow", "red_card"):
        card = {"yellow_card": "yellow", "second_yellow": "second_yellow", "red_card": "red"}[kind]
        return {**base, "type": "foul", "subtype": "foul", "card": card}
    if kind == "substitution":
        return {**base, "type": "substitution", "subtype": "substitution", "player_off_id": e.get("player_off_id")}
    return {**base, "type": "stoppage", "subtype": "whistle", "marker": "period_start"}


def _num(row: dict[str, Any], skip: tuple[str, ...]) -> Row:
    return {k: float(v) for k, v in row.items() if k not in skip and v not in ("", None)}


class LiveMatch:
    """A match built up one minute at a time from the feed."""

    def __init__(self, meta: dict[str, Any]) -> None:
        self.meta = meta
        self.teams = [t["team_id"] for t in meta["teams"]]
        players = [(t["team_id"], p) for t in meta["teams"] for p in t["players"]]
        self.player_team = {p["player_id"]: t for t, p in players}
        self.names = {p["player_id"]: p.get("short_name") or p["name"] for _, p in players}
        self.roles = {p["player_id"]: p.get("role", "") for _, p in players}
        self.team: dict[str, list[Row]] = {t: [] for t in self.teams}
        self.player: dict[str, dict[int, Row]] = {}
        self.events: list[dict[str, Any]] = []
        self.clocks: list[str] = []
        self.missing: set[str] = set()  # our columns the provider never sent
        self._score = {t: 0 for t in self.teams}
        self._reds = {t: 0 for t in self.teams}

    @property
    def minutes(self) -> int:
        return len(self.clocks)

    @property
    def score(self) -> dict[str, int]:
        """The score after every minute received so far."""
        return dict(self._score)

    def add(self, minute: Minute) -> None:
        """Take the next minute. Minutes must arrive in order, with none missing."""
        m = self.minutes
        if minute.m != m:
            raise ValueError(f"expected minute {m}, got {minute.m}")
        events = [_event(e, m) for e in minute.events]
        for t in self.teams:
            raw = minute.team.get(t)
            if raw is None:
                raise ValueError(f"minute {m} has no row for {t}")
            o = self.teams[1] if t == self.teams[0] else self.teams[0]
            row = _num(raw, ("team_id", "clock_minute"))
            row["m"] = float(m)
            row.setdefault("goals_for_before", float(self._score[t]))
            row.setdefault("goals_against_before", float(self._score[o]))
            row.setdefault("players_on", float(11 - self._reds[t]))
            self.missing |= {c for c in TEAM_COLUMNS if c not in row}
            self.team[t].append(row)
        for p in minute.players:
            row = _num(p, ("team_id", "player_id"))
            row["m"] = float(m)
            self.missing |= {f"player.{c}" for c in PLAYER_COLUMNS if c not in row}
            self.player.setdefault(str(p["player_id"]), {})[m] = row
        for e in events:
            if e["type"] == "shot" and e["team_id"] in self._score:
                self._score[e["team_id"]] += 1
            if e.get("card") in ("red", "second_yellow") and e["team_id"] in self._reds:
                self._reds[e["team_id"]] += 1
        self.events.extend(events)
        self.clocks.append(str(minute.team[self.teams[0]].get("clock_minute") or ""))

    @property
    def md(self) -> MatchData:
        """The match as it stands: every minute received so far, nothing else."""
        n = self.minutes
        return MatchData(
            self.meta,
            list(self.events),
            {t: rows[:n] for t, rows in self.team.items()},
            {p: dict(rows) for p, rows in self.player.items()},
            self.player_team,
            self.names,
            self.roles,
            key_events(self.events),
            list(self.clocks),
        )


@dataclass
class Feed:
    """A whole feed read from files, to be played back one minute at a time."""

    meta: dict[str, Any]
    minutes: list[Minute]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.read_text().strip():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def read_feed(folder: Path, mapping: Mapping | None = None) -> Feed:
    """A feed folder: lineups.json, club_minutes.csv, player_minutes.csv and events.csv, in the
    provider's own column names, split back into minutes."""
    mapping = mapping or load_mapping()
    meta = lineup_meta(json.loads((folder / "lineups.json").read_text()), mapping)
    tick = {ours: theirs for theirs, ours in mapping["team"].items()}["m"]
    p_tick = {ours: theirs for theirs, ours in mapping["player"].items()}["m"]
    e_tick = {ours: theirs for theirs, ours in mapping["events"].items()}["m"]
    team: dict[int, list[dict[str, Any]]] = {}
    for r in _read_csv(folder / "club_minutes.csv"):
        team.setdefault(int(r[tick]), []).append(r)
    players: dict[int, list[dict[str, Any]]] = {}
    for r in _read_csv(folder / "player_minutes.csv"):
        players.setdefault(int(r[p_tick]), []).append(r)
    events: dict[int, list[dict[str, Any]]] = {}
    for r in _read_csv(folder / "events.csv"):
        events.setdefault(int(r[e_tick]), []).append(r)
    minutes = [to_minute(m, team[m], players.get(m, []), events.get(m, []), mapping) for m in sorted(team)]
    return Feed(meta, minutes)


# --- writing a feed: what a provider would send for a match we hold in the public format ---

KEEP_META = ("match_id", "competition", "venue", "synthetic", "physical_note", "coordinates")  # no result, no seed


def _feed_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for e in events:
        if e["type"] == "stoppage" and e.get("marker") == "period_start":
            kind = "period_start"
        elif e["type"] == "shot" and e["outcome"] == "goal":
            kind = "goal"
        elif e["type"] == "foul" and e.get("card"):
            kind = {"yellow": "yellow_card", "second_yellow": "second_yellow", "red": "red_card"}[e["card"]]
        elif e["type"] == "substitution":
            kind = "substitution"
        else:
            continue
        out.append(
            {
                "m": e["m"],
                "id": e["id"],
                "period": e["period"],
                "clock": e["clock"],
                "kind": kind,
                "team_id": e["team_id"],
                "player_id": e.get("player_id") or "",
                "player_off_id": e.get("player_off_id") or "",
            }
        )
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]], cols: dict[str, str]) -> None:
    back = {ours: theirs for theirs, ours in cols.items()}
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(back.values()))
        w.writeheader()
        for r in rows:
            w.writerow({back[k]: v for k, v in r.items() if k in back})


def export_feed(match_folder: Path, out: Path, mapping: Mapping | None = None) -> Path:
    """Write a match folder as a provider's feed: per-minute tables and key events only, in the
    provider's column names, without the final score. The raw event stream stays behind."""
    mapping = mapping or load_mapping()
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((match_folder / "match.json").read_text())
    back = {ours: theirs for theirs, ours in mapping["lineup"].items()}
    lineup = {k: meta[k] for k in KEEP_META if k in meta}
    lineup["teams"] = [
        {
            **{k: v for k, v in t.items() if k != "players"},
            "players": [{back.get(k, k): v for k, v in p.items() if k in back} for p in t["players"]],
        }
        for t in meta["teams"]
    ]
    (out / "lineups.json").write_text(json.dumps(lineup, indent=1) + "\n")
    team_cols = {k: v for k, v in mapping["team"].items() if v not in DERIVED}
    _write_csv(out / "club_minutes.csv", _read_csv(match_folder / "team_minute.csv"), team_cols)
    _write_csv(out / "player_minutes.csv", _read_csv(match_folder / "player_minute.csv"), mapping["player"])
    events = [json.loads(line) for line in (match_folder / "events.jsonl").read_text().splitlines() if line.strip()]
    kinds = {ours: theirs for theirs, ours in mapping["kinds"].items()}
    rows = [{**e, "kind": kinds.get(e["kind"], e["kind"])} for e in _feed_events(events)]
    _write_csv(out / "events.csv", rows, mapping["events"])
    return out
