"""Teams, players and plans: the state the match engine plays with."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parents[2] / "data"

# League role -> (Wyscout role family, lateral slot 0-100 in the attacking frame; y < 50 is the left)
ROLES: dict[str, tuple[str, float]] = {
    "GK": ("GK", 50),
    "CB": ("DF", 50),
    "RB": ("DF", 85),
    "LB": ("DF", 15),
    "FB": ("DF", 85),
    "RWB": ("DF", 88),
    "LWB": ("DF", 12),
    "DM": ("MD", 50),
    "CM": ("MD", 50),
    "AM": ("MD", 50),
    "RM": ("MD", 82),
    "LM": ("MD", 18),
    "RW": ("FW", 80),
    "LW": ("FW", 20),
    "W": ("FW", 80),
    "ST": ("FW", 50),
}


@dataclass
class Plan:
    """How a team is set up to play. 0 is league average on every axis; roughly -1 to +1."""

    block: float = 0.0  # how high the team engages out of possession
    press: float = 0.0  # how hard it presses where it engages
    directness: float = 0.0  # long balls instead of short build-up
    tempo: float = 0.0  # speed of circulation
    width: float = 0.0  # wide play and crosses
    risk: float = 0.0  # forward passes, take-ons, through balls
    aggression: float = 0.0  # duels and fouls
    shoot: float = 0.0  # willingness to shoot
    waste: float = 0.0  # slowing restarts (game management)

    def copy(self) -> Plan:
        return Plan(**asdict(self))

    def toward(self, target: Plan, step: float) -> None:
        for f in fields(self):
            a, b = getattr(self, f.name), getattr(target, f.name)
            setattr(self, f.name, b if abs(b - a) <= step else a + step * (1 if b > a else -1))

    def shifted(self, **delta: float) -> Plan:
        p = self.copy()
        for k, v in delta.items():
            setattr(p, k, max(-1.5, min(1.5, getattr(p, k) + v)))
        return p

    def rounded(self) -> dict[str, float]:
        return {k: round(v, 3) for k, v in asdict(self).items()}


@dataclass
class PlayerState:
    player_id: str
    name: str
    short_name: str
    shirt: int
    role: str
    family: str
    slot_y: float
    attrs: dict[str, float]
    on: bool = False
    starter: bool = False
    on_at: float | None = None  # continuous match seconds
    off_at: float | None = None
    fresh: float = 1.0
    load: float = 0.0
    yellows: int = 0
    sent_off: bool = False

    @property
    def pass_q(self) -> float:
        return (self.attrs.get("passing", 70) * 0.7 + self.attrs.get("vision", 70) * 0.3 - 70) / 15

    @property
    def duel_q(self) -> float:
        a = self.attrs
        return (a.get("tackling", 65) * 0.5 + a.get("pace", 70) * 0.25 + a.get("acceleration", 70) * 0.25 - 68) / 15

    @property
    def finish_q(self) -> float:
        return (self.attrs.get("finishing", 60) - 70) / 20

    @property
    def keep_q(self) -> float:
        return (self.attrs.get("keeping", 80) - 80) / 25

    @property
    def stamina(self) -> float:
        return self.attrs.get("stamina", 75)


@dataclass
class TeamState:
    team_id: str
    name: str
    short_name: str
    rating: float
    formation: str
    colours: dict[str, str]
    style: Plan
    players: list[PlayerState]
    home: bool
    plan: Plan = field(default_factory=Plan)
    target: Plan = field(default_factory=Plan)
    flow: float = 0.0
    score: int = 0

    @property
    def quality(self) -> float:
        return (self.rating - 70) / 5

    @property
    def on_pitch(self) -> list[PlayerState]:
        return [p for p in self.players if p.on]

    @property
    def count(self) -> int:
        return len(self.on_pitch)

    @property
    def fresh(self) -> float:
        out = [p.fresh for p in self.on_pitch if p.family != "GK"]
        return sum(out) / len(out) if out else 1.0

    def meta(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "short_name": self.short_name,
            "home": self.home,
            "formation": self.formation,
            "colours": self.colours,
            "players": [
                {
                    "player_id": p.player_id,
                    "name": p.name,
                    "short_name": p.short_name,
                    "shirt": p.shirt,
                    "role": p.role,
                    "position": p.family,
                    "starter": p.starter,
                }
                for p in self.players
            ],
        }


def club_style(club: dict[str, Any]) -> Plan:
    """A stable, plausible playing style for a fictional club, if data/styles.json does not set one."""
    styles = DATA / "styles.json"
    if styles.exists():
        s = json.loads(styles.read_text()).get(club["team_id"])
        if s:
            return Plan(**s)
    seed = int(hashlib.sha256(club["team_id"].encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    q = (club["rating"] - 70) / 6
    return Plan(
        block=round(0.35 * q + rng.gauss(0, 0.35), 2),
        press=round(0.3 * q + rng.gauss(0, 0.35), 2),
        directness=round(-0.5 * q + rng.gauss(0, 0.6), 2),
        tempo=round(0.2 * q + rng.gauss(0, 0.3), 2),
        width=round(rng.gauss(0, 0.35), 2),
        risk=round(0.15 * q + rng.gauss(0, 0.3), 2),
        aggression=round(rng.gauss(0, 0.35), 2),
        shoot=round(rng.gauss(0, 0.25), 2),
    )


def load_league(path: Path | None = None) -> dict[str, Any]:
    league: dict[str, Any] = json.loads((path or DATA / "league.json").read_text())
    return league


def build_team(club: dict[str, Any], home: bool, style: Plan | None = None) -> TeamState:
    players = []
    for i, p in enumerate(club["squad"]):
        family, slot = ROLES.get(p["role"], ("MD", 50))
        players.append(
            PlayerState(
                player_id=p["player_id"],
                name=p["name"],
                short_name=p.get("short_name", p["name"]),
                shirt=p["shirt"],
                role=p["role"],
                family=family,
                slot_y=slot,
                attrs={k: float(v) for k, v in p["attributes"].items()},
                on=i < 11,
                starter=i < 11,
                on_at=0.0 if i < 11 else None,
            )
        )
    st = style or club_style(club)
    return TeamState(
        team_id=club["team_id"],
        name=club["name"],
        short_name=club.get("short_name", club["name"]),
        rating=float(club["rating"]),
        formation=club.get("formation", "4-3-3"),
        colours=club.get("colours", {}),
        style=st,
        players=players,
        home=home,
        plan=st.copy(),
        target=st.copy(),
    )
