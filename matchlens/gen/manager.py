"""The coaching layer: decisions that change how a team plays, logged as hidden ground truth.

Events only *sometimes* lead to a change of plan, with probabilities set from real-season effects
(docs/research/real-momentum-patterns.md). Plans can also change with no event at all (an
instruction from the touchline, a tweak), and fatigue and a drifting flow term act continuously.
Nothing here sets momentum. The agents never see this log; it exists to score them.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from .model import Plan, PlayerState, TeamState

if TYPE_CHECKING:
    from .engine import Match

INSTRUCTIONS: dict[str, dict[str, float]] = {
    "press_higher": {"block": 0.6, "press": 0.6},
    "drop_deeper": {"block": -0.6, "press": -0.5},
    "go_direct": {"directness": 0.8, "tempo": 0.3},
    "build_patiently": {"directness": -0.6, "tempo": -0.2, "risk": -0.2},
    "attack_wide": {"width": 0.7, "directness": 0.2},
    "push_for_goal": {"block": 0.5, "press": 0.4, "risk": 0.5, "directness": 0.3, "shoot": 0.4},
    "park_the_bus": {"block": -0.9, "press": -0.6, "directness": 0.5, "risk": -0.4, "waste": 0.6},
    "protect_lead": {"block": -0.5, "press": -0.3, "waste": 0.8, "risk": -0.3},
    "calm_it_down": {"tempo": -0.4, "aggression": -0.4},
    "get_stuck_in": {"aggression": 0.6, "press": 0.3},
}
BY_STATE = {
    "losing": ["push_for_goal", "press_higher", "go_direct", "attack_wide", "get_stuck_in"],
    "level": ["press_higher", "drop_deeper", "go_direct", "build_patiently", "attack_wide", "get_stuck_in", "calm_it_down"],
    "winning": ["drop_deeper", "build_patiently", "protect_lead", "calm_it_down", "press_higher"],
}
RESPONSES = {
    "press_higher": ["go_direct"],
    "park_the_bus": ["attack_wide", "push_for_goal"],
    "drop_deeper": ["press_higher", "attack_wide"],
    "push_for_goal": ["drop_deeper", "go_direct"],
    "go_direct": ["drop_deeper"],
    "protect_lead": ["push_for_goal"],
    "attack_wide": ["drop_deeper"],
    "get_stuck_in": ["calm_it_down"],
    "build_patiently": ["press_higher"],
    "calm_it_down": [],
}

FLOW_TAU = 3.0  # minutes
FLOW_SD = 0.40  # logit units; calibrated by the realism gate
PLAN_STEP = 0.3  # how fast a new plan takes effect, per minute
P_RED_RESHAPE = 0.73
P_HALF_TIME = 0.15
SPONTANEOUS_PER_MATCH = 0.5


class Manager:
    def __init__(self, match: Match) -> None:
        self.m = match
        self.rng = random.Random(match.seed * 7919 + 17)
        self.decisions: list[dict[str, Any]] = []
        self.minutes: list[dict[str, Any]] = []
        self.pending: list[tuple[int, TeamState, str, dict[str, Any]]] = []
        self.sub_minutes: dict[str, list[int]] = {}
        self.faded: set[str] = set()
        self.protecting: set[str] = set()
        self._started = False

    # ---- helpers -------------------------------------------------------------------------
    def state(self, team: TeamState) -> str:
        d = team.score - self.m.other(team).score
        return "losing" if d < 0 else "winning" if d > 0 else "level"

    def decide(
        self, team: TeamState, kind: str, trigger: dict[str, Any], m: int | None = None, respond: bool = True
    ) -> dict[str, Any]:
        delta = INSTRUCTIONS.get(kind, {})
        team.target = team.target.shifted(**delta)
        rec: dict[str, Any] = {
            "id": f"{self.m.match_id}-x{len(self.decisions) + 1:03d}",
            "m": self.now() if m is None else m,
            "clock": self.m.clock(),
            "team_id": team.team_id,
            "kind": kind,
            "trigger": trigger,
            "change": delta,
            "score": f"{self.m.home.score}-{self.m.away.score}",
        }
        self.decisions.append(rec)
        if respond and delta and self.rng.random() < 0.3:
            opts = RESPONSES.get(kind, [])
            if opts:
                due = rec["m"] + self.rng.randint(3, 8)
                self.pending.append((due, self.m.other(team), self.rng.choice(opts), {"kind": "response", "to": rec["id"]}))
        return rec

    def now(self) -> int:
        return int(self.m.t_abs // 60)

    # ---- hooks from the engine -----------------------------------------------------------
    def start(self) -> None:
        pr = self.m.pr
        for team in (self.m.home, self.m.away):
            counts = pr.subs["count"]
            n = int(self.rng.choices(list(counts), weights=list(counts.values()))[0])
            mins = sorted(int(pr.sample_quantile(self.rng, pr.subs["minute_by_order"][str(i)][1:-1])) for i in range(n))
            self.sub_minutes[team.team_id] = [max(46, x) for x in mins]
        self._started = True

    def minute(self, m: int) -> None:
        if not self._started:
            self.start()
        a = math.exp(-1 / FLOW_TAU)
        for team in (self.m.home, self.m.away):
            team.flow = team.flow * a + FLOW_SD * math.sqrt(1 - a * a) * self.rng.gauss(0, 1)
            self.fatigue(team)
            team.plan.toward(self.with_score(team, m), PLAN_STEP)
        for team in (self.m.home, self.m.away):
            for due in list(self.sub_minutes[team.team_id]):
                if m + 1 >= due:
                    self.sub_minutes[team.team_id].remove(due)
                    self.substitute(team, m)
            if 20 <= m <= 85 and self.rng.random() < SPONTANEOUS_PER_MATCH / 65:
                self.decide(team, self.rng.choice(BY_STATE[self.state(team)]), {"kind": "none"}, m)
            if m >= 75 and self.state(team) == "winning" and team.team_id not in self.protecting and self.rng.random() < 0.06:
                self.protecting.add(team.team_id)
                self.decide(team, "protect_lead", {"kind": "game_state"}, m)
            if team.team_id not in self.faded and team.fresh < 0.84:
                self.faded.add(team.team_id)
                self.decisions.append(
                    {
                        "id": f"{self.m.match_id}-x{len(self.decisions) + 1:03d}",
                        "m": m,
                        "clock": self.m.clock(),
                        "team_id": team.team_id,
                        "kind": "fatigue_fade",
                        "trigger": {"kind": "none"},
                        "change": {},
                        "score": f"{self.m.home.score}-{self.m.away.score}",
                    }
                )
        for item in [p for p in self.pending if p[0] <= m]:
            self.pending.remove(item)
            self.decide(item[1], item[2], item[3], m, respond=False)
        self.minutes.append(
            {
                "m": m,
                "score": [self.m.home.score, self.m.away.score],
                "teams": {
                    t.team_id: {
                        "plan": t.plan.rounded(),
                        "flow": round(t.flow, 3),
                        "fresh": round(t.fresh, 3),
                        "players": t.count,
                    }
                    for t in (self.m.home, self.m.away)
                },
            }
        )

    def with_score(self, team: TeamState, m: int) -> Plan:
        """Score effects: trailing teams push and take risks, leading teams sit deeper, more so as time runs out."""
        d = team.score - self.m.other(team).score
        if d == 0:
            return team.target
        w = (0.4 + 0.6 * min(m, 90) / 90) * min(abs(d), 2) ** 0.5
        if d > 0:
            return team.target.shifted(block=-0.4 * w, press=-0.35 * w, risk=-0.25 * w, directness=0.15 * w)
        return team.target.shifted(block=0.4 * w, press=0.3 * w, risk=0.35 * w, directness=0.2 * w, shoot=0.2 * w)

    def fatigue(self, team: TeamState) -> None:
        pl = team.plan
        work = 1 + 0.35 * max(0.0, pl.press) + 0.2 * max(0.0, pl.tempo) + 0.15 * max(0.0, pl.block)
        for p in team.on_pitch:
            if p.family == "GK":
                continue
            p.load += work * 75 / max(40.0, p.stamina)
            p.fresh = 1 - 0.25 * (p.load / 90) ** 1.5

    def substitute(self, team: TeamState, m: int) -> None:
        bench = [p for p in team.players if not p.on and not p.starter and p.off_at is None and p.family != "GK"]
        outfield = [p for p in team.on_pitch if p.family != "GK"]
        if not bench or not outfield:
            return
        state = self.state(team)
        tired = sorted(outfield, key=lambda p: p.fresh + self.rng.gauss(0, 0.05))
        off = tired[0]
        plan_kind = None
        if state == "losing" and m >= 55:
            fw = [p for p in bench if p.family == "FW"]
            on = self.rng.choice(fw) if fw and self.rng.random() < 0.6 else self.like_for_like(bench, off)
            if self.rng.random() < 0.45:
                plan_kind = "push_for_goal"
        elif state == "winning" and m >= 70:
            df = [p for p in bench if p.family in ("DF", "MD")]
            on = self.rng.choice(df) if df and self.rng.random() < 0.5 else self.like_for_like(bench, off)
            if self.rng.random() < 0.35:
                plan_kind = "protect_lead"
        else:
            on = self.like_for_like(bench, off)
        t = self.m.t_abs
        off.on, off.off_at = False, t
        on.on, on.on_at, on.fresh, on.load = True, t, 1.0, 0.0
        on.slot_y = off.slot_y
        idx = self.m.write("Substitution", team, on, 50, 0, 50, 0, "", player_off_id=off.player_id)
        ev = self.m.events[idx]
        ev["type"], ev["subtype"] = "substitution", "substitution"
        rec = {
            "id": f"{self.m.match_id}-x{len(self.decisions) + 1:03d}",
            "m": m,
            "clock": self.m.clock(),
            "team_id": team.team_id,
            "kind": "substitution",
            "trigger": {"kind": "substitution", "event_id": ev["id"]},
            "change": {},
            "player_on": on.player_id,
            "player_off": off.player_id,
            "fresh_off": round(off.fresh, 3),
            "score": f"{self.m.home.score}-{self.m.away.score}",
        }
        self.decisions.append(rec)
        if plan_kind:
            self.decide(team, plan_kind, {"kind": "substitution", "event_id": ev["id"]}, m)

    def like_for_like(self, bench: list[PlayerState], off: PlayerState) -> PlayerState:
        same = [p for p in bench if p.family == off.family]
        return self.rng.choice(same or bench)

    def on_goal(self, scorer: TeamState, ev: dict[str, Any]) -> None:
        m = self.now()
        conceder = self.m.other(scorer)
        if m < 88 and self.state(conceder) != "winning" and self.rng.random() < 0.15 + 0.25 * m / 90:
            self.decide(conceder, "push_for_goal", {"kind": "goal", "event_id": ev["id"]})
        if m > 55 and self.state(scorer) == "winning" and self.rng.random() < 0.15 + 0.35 * (m - 55) / 35:
            self.protecting.add(scorer.team_id)
            self.decide(scorer, "protect_lead", {"kind": "goal", "event_id": ev["id"]})

    def on_red(self, team: TeamState, player: PlayerState, ev: dict[str, Any]) -> None:
        trig = {"kind": "red_card", "event_id": ev["id"], "player_id": player.player_id}
        if self.rng.random() < P_RED_RESHAPE:
            self.decide(team, "park_the_bus" if self.now() < 80 else "drop_deeper", trig)
        else:
            self.decisions.append(
                {
                    "id": f"{self.m.match_id}-x{len(self.decisions) + 1:03d}",
                    "m": self.now(),
                    "clock": self.m.clock(),
                    "team_id": team.team_id,
                    "kind": "keep_shape",
                    "trigger": trig,
                    "change": {},
                    "score": f"{self.m.home.score}-{self.m.away.score}",
                }
            )

    def half_time(self) -> None:
        for team in (self.m.home, self.m.away):
            if self.rng.random() < P_HALF_TIME:
                self.decide(team, self.rng.choice(BY_STATE[self.state(team)]), {"kind": "half_time"}, self.now())

    def after_event(self, ev: dict[str, Any]) -> None:
        return None

    def full_time(self) -> None:
        return None
