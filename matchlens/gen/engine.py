"""The match engine: plays a synthetic match action by action.

Each step samples the next action from transitions learned from real matches (see
research/learn_priors.py), reweighted by both teams' current plans, player quality, fatigue,
numbers on the pitch and a slowly drifting "flow" term. Nothing here writes momentum: possession,
territory and momentum emerge from the actions. Coaching decisions live in manager.py.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from .manager import Manager
from .model import PlayerState, TeamState
from .physical import Physical
from .priors import Priors, Weighted, load_priors, zone

PASS_TYPES = {"Simple pass", "High pass", "Head pass", "Cross", "Launch", "Smart pass", "Hand pass"}
SET_PASSES = {"Free Kick", "Free kick cross", "Corner", "Throw in", "Goal kick"}
CONTESTS = {"Ground duel", "Loose duel", "Air duel"}
SHOTS = {"Shot", "Free kick shot", "Penalty"}
MOVES = PASS_TYPES | SET_PASSES | CONTESTS | {"Clearance", "Acceleration", "Touch"}
DEAD = {"Ball out", "Whistle", "Foul", "Offside"}
AERIAL_DELIVERY = {"Cross", "High pass", "Corner", "Free kick cross", "Air duel", "Launch", "Head pass"}

# How the learned token types are written out: (type, subtype)
OUT_NAMES: dict[str, tuple[str, str]] = {
    "Simple pass": ("pass", "short"),
    "High pass": ("pass", "high"),
    "Head pass": ("pass", "header"),
    "Cross": ("pass", "cross"),
    "Launch": ("pass", "long"),
    "Smart pass": ("pass", "through"),
    "Hand pass": ("pass", "throw"),
    "Free Kick": ("pass", "free_kick"),
    "Free kick cross": ("pass", "free_kick_cross"),
    "Corner": ("pass", "corner"),
    "Throw in": ("pass", "throw_in"),
    "Goal kick": ("pass", "goal_kick"),
    "Ground duel": ("duel", "ground"),
    "Loose duel": ("duel", "loose_ball"),
    "Air duel": ("duel", "aerial"),
    "Acceleration": ("carry", "carry"),
    "Touch": ("touch", "touch"),
    "Clearance": ("clearance", "clearance"),
    "Shot": ("shot", "open_play"),
    "Free kick shot": ("shot", "free_kick"),
    "Penalty": ("shot", "penalty"),
    "Foul": ("foul", "foul"),
    "Ball out": ("ball_out", "ball_out"),
    "Whistle": ("stoppage", "whistle"),
    "Offside": ("offside", "offside"),
    "Save": ("save", "save"),
    "GK out": ("keeper_sweep", "keeper_sweep"),
}

# Tuning constants (calibrated against the real season by the realism gate)
K_QUALITY_PASS = 0.18
K_QUALITY_DUEL = 0.6
K_HOME = 0.3
K_PRESS_CONTEST = 1.1
K_PRESS_PASS = 0.9
K_NUMBERS = 1.8
DT_SCALE = 0.91
K_SHOT = -0.65
K_FINISH = -0.35
K_FWD_RISK = 0.3
K_FWD_BASE = -0.3
K_FWD_BLOCK = 0.25
K_FWD_FLOW = 0.4
K_ENGAGE_FLOW = 8.0
K_FINAL_BLOCK = 0.4
P_SECOND_YELLOW = 0.15
K_PASS = 0.1
K_CONTEST = -0.2
K_FOUL = -0.1


@dataclass
class Tok:
    typ: str
    out: str
    team: TeamState
    player: PlayerState | None
    sx: float
    sy: float
    ex: float
    ey: float
    event_index: int


def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def clip(v: float) -> float:
    return min(max(v, 0.0), 100.0)


class Match:
    def __init__(
        self,
        match_id: str,
        home: TeamState,
        away: TeamState,
        seed: int,
        priors: Priors | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.match_id = match_id
        self.home, self.away = home, away
        self.rng = random.Random(seed)
        self.seed = seed
        self.pr = priors or load_priors()
        self.meta = meta or {}
        self.events: list[dict[str, Any]] = []
        self.period = 1
        self.sec = 0.0
        self.first_half_len = 0.0
        self.minute_done = -1
        self.possession = 0
        self.poss_team: TeamState | None = None
        self.bip_acc = 0.0
        self.manager = Manager(self)
        self.physical = Physical(self)

    # ---- helpers -------------------------------------------------------------------------
    def other(self, t: TeamState) -> TeamState:
        return self.away if t is self.home else self.home

    @property
    def t_abs(self) -> float:
        return self.sec + (self.first_half_len if self.period == 2 else 0.0)

    def clock(self) -> str:
        base = 45 * (self.period - 1)
        m, s = int(self.sec // 60), int(self.sec % 60)
        if m >= 45:
            return f"{base + 45}+{m - 44}:{s:02d}"
        return f"{base + m}:{s:02d}"

    def press_effect(self, defending: TeamState, x_att: float) -> float:
        """Extra pressure the defending team applies at x (attacking team's frame), against league average."""
        engage = 55 + 20 * defending.plan.block + K_ENGAGE_FLOW * (defending.flow - self.other(defending).flow)
        intensity = (1 + 0.6 * defending.plan.press) * (0.55 + 0.45 * defending.fresh)
        if defending.count < 11:
            intensity *= 0.85
        return intensity * sigmoid((x_att - (100 - engage)) / 7) - sigmoid((x_att - 45) / 7)

    def numbers(self, a: TeamState) -> int:
        return self.other(a).count - a.count

    # ---- player selection ----------------------------------------------------------------
    def pick(
        self, team: TeamState, typ: str, x: float, y: float, exclude: PlayerState | None = None, table: str = "roles"
    ) -> PlayerState:
        shares = getattr(self.pr, table).get(f"{typ}|{zone(x, y)}") or {"MD": 1}
        on = team.on_pitch
        fam_count: dict[str, int] = {}
        for p in on:
            fam_count[p.family] = fam_count.get(p.family, 0) + 1
        total = sum(shares.values())
        weights = {}
        for p in on:
            if p is exclude and len(on) > 1:
                continue
            share = shares.get(p.family, 0) / total
            if share == 0:
                share = 0.002 if p.family != "GK" else 0.0
            lat = math.exp(-((y - p.slot_y) ** 2) / (2 * 26**2)) + 0.12
            w = share / fam_count[p.family] * lat
            if typ in CONTESTS or typ == "Foul":
                w *= p.fresh**1.3
            else:
                w *= 0.6 + 0.4 * p.fresh
            weights[p.player_id] = w
        if not weights:
            return on[0]
        pid = Weighted(weights).sample(self.rng)
        return next(p for p in on if p.player_id == pid)

    # ---- event writing -------------------------------------------------------------------
    def write(
        self,
        typ: str,
        team: TeamState,
        player: PlayerState | None,
        sx: float,
        sy: float,
        ex: float,
        ey: float,
        outcome: str,
        **q: Any,
    ) -> int:
        kind, sub = OUT_NAMES.get(typ, (typ.lower(), typ.lower()))
        if kind in ("pass", "carry", "shot", "touch") and self.poss_team is not team:
            self.possession += 1
            self.poss_team = team
        ev = {
            "id": f"{self.match_id}-e{len(self.events) + 1:05d}",
            "period": self.period,
            "t": round(self.sec, 2),
            "m": int(self.t_abs // 60),
            "clock": self.clock(),
            "team_id": team.team_id,
            "player_id": player.player_id if player else None,
            "type": kind,
            "subtype": sub,
            "x": round(sx * 1.05, 1),
            "y": round(sy * 0.68, 1),
            "end_x": round(ex * 1.05, 1),
            "end_y": round(ey * 0.68, 1),
            "outcome": outcome,
            "possession": self.possession,
        }
        ev.update({k: v for k, v in q.items() if v is not None})
        self.events.append(ev)
        return len(self.events) - 1

    # ---- one action ----------------------------------------------------------------------
    def act(self, typ: str, team: TeamState, x: float, y: float, prev: Tok | None) -> Tok:
        opp = self.other(team)
        rng = self.rng
        z = zone(x, y)
        same = prev is not None and prev.team is team
        # who acts
        carrier = None
        if same and prev is not None and prev.player is not None and prev.player.on:
            if prev.typ in ("Acceleration", "Touch") or (prev.typ in CONTESTS and prev.out == "ok"):
                carrier = prev.player
        if typ == "Save" or typ == "GK out":
            keepers = [p for p in team.on_pitch if p.family == "GK"]
            player = keepers[0] if keepers else self.pick(team, typ, x, y)
        elif carrier is not None and (typ in PASS_TYPES or typ in SHOTS or typ in ("Acceleration", "Touch", "Clearance")):
            player = carrier
        else:
            exclude = prev.player if (same and prev is not None and prev.typ in PASS_TYPES | SET_PASSES) else None
            player = self.pick(team, typ, x, y, exclude=exclude)
        # receiver of the previous pass
        if same and prev is not None and prev.typ in PASS_TYPES | SET_PASSES and prev.out == "ok" and prev.player is not player:
            self.events[prev.event_index]["receiver_id"] = player.player_id

        ex, ey = x, y
        if typ in MOVES:
            cands = self.pr.displacement(typ, z)
            wscale = team.plan.width
            fwd = K_FWD_BASE + K_FWD_RISK * team.plan.risk + K_FWD_BLOCK * team.plan.block + K_FWD_FLOW * (team.flow - opp.flow)
            if typ in PASS_TYPES or typ == "Acceleration":
                weights = {
                    f"{i}": c * math.exp(wscale * (abs(y + dy - 50) - 25) / 25 + fwd * dx / 30)
                    for i, (dx, dy, c) in enumerate(cands)
                }
            else:
                weights = {f"{i}": c for i, (_, _, c) in enumerate(cands)}
            dx, dy, _ = cands[int(Weighted(weights).sample(rng))]
            ex, ey = clip(x + dx + rng.uniform(-1, 1)), clip(y + dy + rng.uniform(-1, 1))

        flow = team.flow - opp.flow
        out = ""
        idx: int
        if typ in PASS_TYPES or typ in SET_PASSES:
            p0 = self.pr.pass_success(typ, z, ex - x, ey - y)
            adj = (
                K_PASS
                + K_QUALITY_PASS * (team.quality - opp.quality)
                + (K_HOME if team.home else -K_HOME)
                + 0.15 * player.pass_q
                + flow
                - K_PRESS_PASS * self.press_effect(opp, x)
                - K_NUMBERS * self.numbers(team) * 0.6
                + 0.35 * (player.fresh - 1)
                - 0.12 * team.plan.risk
                + (K_FINAL_BLOCK * team.plan.block if x >= 200 / 3 else 0.0)
            )
            out = "ok" if rng.random() < sigmoid(logit(p0) + adj) else "ko"
            idx = self.write(
                typ,
                team,
                player,
                x,
                y,
                ex,
                ey,
                "complete" if out == "ok" else "incomplete",
                kick_off=True if prev is None else None,
            )
        elif typ in CONTESTS:
            o = self.pick(opp, typ, 100 - x, 100 - y, table="opp_roles")
            pw, pn = self.pr.contest_base(typ, z)
            adj = (
                K_QUALITY_DUEL * (team.quality - opp.quality)
                + 0.35 * (player.duel_q - o.duel_q)
                + 0.8 * (player.fresh - o.fresh)
                + 0.7 * flow
                - K_NUMBERS * self.numbers(team)
                + (K_HOME if team.home else -K_HOME) * 0.5
                + 0.12 * (team.plan.aggression - opp.plan.aggression)
            )
            r = rng.random()
            if r < pn:
                out = "nt"
            else:
                out = "ok" if rng.random() < sigmoid(logit(pw / (1 - pn)) + adj) else "ko"
            mine = {"ok": "won", "ko": "lost", "nt": "neutral"}[out]
            theirs = {"ok": "lost", "ko": "won", "nt": "neutral"}[out]
            duel_id = f"{self.match_id}-d{len(self.events) + 1:05d}"
            ground = typ == "Ground duel"
            idx = self.write(
                typ,
                team,
                player,
                x,
                y,
                ex,
                ey,
                mine,
                duel_id=duel_id,
                opponent_id=o.player_id,
                duel_role="attacking" if ground else None,
            )
            self.write(
                typ,
                opp,
                o,
                100 - x,
                100 - y,
                100 - ex,
                100 - ey,
                theirs,
                duel_id=duel_id,
                opponent_id=player.player_id,
                duel_role="defending" if ground else None,
            )
        elif typ in SHOTS:
            header = typ == "Shot" and prev is not None and prev.typ in AERIAL_DELIVERY and rng.random() < 0.55
            gk = next((p for p in opp.on_pitch if p.family == "GK"), None)
            if typ == "Penalty":
                xg = self.pr.penalty_xg
            else:
                xg = self.pr.xg(x, y, header) * (0.55 if typ == "Free kick shot" else 1.0)
            pg = sigmoid(logit(xg) + K_FINISH + 0.5 * player.finish_q - (0.5 * gk.keep_q if gk else -0.5) + 0.25 * flow)
            if rng.random() < pg:
                out = "goal"
            else:
                d = math.hypot((100 - x) * 1.05, (y - 50) * 0.68)
                key = "fk" if typ == "Free kick shot" else ("near" if d < 12 else "mid" if d < 20 else "far")
                out = self.pr.shot_miss[key].sample(rng) if typ != "Penalty" else rng.choice(["saved", "saved", "off"])
            ex, ey = 100.0, 50 + rng.uniform(-6, 6)
            idx = self.write(typ, team, player, x, y, ex, ey, out, xg=round(xg, 3), header=header or None)
            if out == "goal":
                team.score += 1
                self.manager.on_goal(team, self.events[idx])
        elif typ == "Foul":
            card = ""
            a = team.plan.aggression
            r = rng.random()
            yl = self.pr.card_rates.get("yellow", 0.13) * math.exp(0.4 * a)
            rd = self.pr.card_rates.get("red", 0.003) * math.exp(0.4 * a)
            if r < rd:
                card = "red"
            elif r < rd + yl:
                if player.yellows == 0:
                    card = "yellow"
                elif rng.random() < P_SECOND_YELLOW:
                    card = "second_yellow"
            out = card
            idx = self.write(typ, team, player, x, y, x, y, "foul", card=card or None)
            if card == "yellow":
                player.yellows += 1
            elif card in ("red", "second_yellow"):
                player.on = False
                player.sent_off = True
                player.off_at = self.t_abs
                self.manager.on_red(team, player, self.events[idx])
        else:
            idx = self.write(typ, team, player if typ not in ("Ball out", "Whistle") else None, x, y, ex, ey, "")
        return Tok(typ, out, team, player, x, y, ex, ey, idx)

    # ---- the next action -----------------------------------------------------------------
    def next_action(self, cur: Tok) -> tuple[str, TeamState]:
        P, D = cur.team, self.other(cur.team)
        counts = self.pr.next_counts(cur.typ, cur.out, zone(cur.ex, cur.ey))
        eff = self.press_effect(D, cur.ex)
        w: dict[str, float] = {}
        for key, c in counts.items():
            typ, rel = key.split("|")
            T = P if rel == "same" else D
            f = 1.0
            if typ in CONTESTS:
                f *= math.exp(K_CONTEST + K_PRESS_CONTEST * eff + 0.25 * max(0, self.numbers(P)))
            if T is P:
                pl = P.plan
                if typ in ("Launch", "High pass"):
                    f *= math.exp(1.0 * pl.directness)
                elif typ == "Simple pass":
                    f *= math.exp(-0.4 * pl.directness + 0.15 * pl.tempo)
                elif typ == "Smart pass":
                    f *= math.exp(0.7 * pl.risk)
                elif typ == "Cross":
                    f *= math.exp(0.6 * pl.width + 0.25 * pl.directness)
                elif typ == "Acceleration":
                    f *= math.exp(0.4 * pl.risk + 0.25 * pl.tempo)
                elif typ == "Shot":
                    f *= math.exp(
                        K_SHOT + 0.5 * pl.shoot + 0.5 * P.flow + 0.15 * (P.quality - D.quality) + (0.1 if P.home else -0.1)
                    )
            if typ == "Foul" and T is D:
                f *= math.exp(K_FOUL + 0.6 * D.plan.aggression + 0.4 * max(0.0, eff))
            w[key] = c * f
        key = Weighted(w).sample(self.rng)
        typ, rel = key.split("|")
        return typ, (P if rel == "same" else D)

    def place(self, typ: str, team: TeamState, cur: Tok) -> tuple[float, float]:
        x, y = (cur.ex, cur.ey) if team is cur.team else (100 - cur.ex, 100 - cur.ey)
        if typ == "Throw in":
            return x, 0.0 if y < 50 else 100.0
        if typ == "Corner":
            return 100.0, 0.0 if y < 50 else 100.0
        if typ == "Goal kick":
            return 5.0, 50.0
        if typ == "Penalty":
            return 89.5, 50.0
        if typ in ("Save", "GK out") and cur.typ in SHOTS:
            return 3.0, 50.0
        return x, y

    # ---- time ----------------------------------------------------------------------------
    def advance(self, dt: float) -> None:
        end = self.sec + dt
        while True:
            next_min = (math.floor(self.t_abs / 60) + 1) * 60 - (self.first_half_len if self.period == 2 else 0)
            if next_min > end:
                break
            self.sec = next_min
            self.tick()
        self.sec = end

    def tick(self) -> None:
        m = int(round(self.t_abs / 60)) - 1
        if m <= self.minute_done:
            return
        self.minute_done = m
        self.physical.minute(m, self.bip_acc)
        self.bip_acc = 0.0
        self.manager.minute(m)

    # ---- the match -----------------------------------------------------------------------
    def play(self) -> None:
        for period in (1, 2):
            self.period = period
            self.sec = 0.0
            length = self.pr.sample_quantile(self.rng, self.pr.half_length[f"{period}H"][:-1])
            kicker = self.home if period == 1 else self.away
            self.write("Whistle", kicker, None, 50, 50, 50, 50, "", marker="period_start")
            if period == 2:
                self.manager.half_time()
            cur = self.act("Simple pass", kicker, 50, 50, None)
            while True:
                typ, team = self.next_action(cur)
                dt = self.pr.sample_dt(self.rng, cur.typ, typ) * DT_SCALE
                if cur.typ in PASS_TYPES | {"Acceleration", "Touch"} and typ in PASS_TYPES | {"Acceleration"}:
                    dt *= math.exp(-0.18 * cur.team.plan.tempo) * (1 + 0.6 * (1 - cur.team.fresh))
                if typ in SET_PASSES and cur.team.plan.waste > 0 and team is cur.team:
                    dt *= 1 + 0.8 * cur.team.plan.waste
                if cur.out == "goal":
                    dt = 50 + self.rng.random() * 40
                live = cur.typ not in DEAD and cur.out != "goal"
                self.bip_acc += dt if live and dt < 15 else min(dt, 2.0)
                self.advance(dt)
                if self.sec >= length and (not live or self.sec >= length + 20):
                    break
                if cur.out == "goal":
                    scorer = cur.team
                    cur = self.act("Simple pass", self.other(scorer), 50, 50, None)
                    self.events[cur.event_index]["kick_off"] = True
                    continue
                x, y = self.place(typ, team, cur)
                cur = self.act(typ, team, x, y, cur)
                self.manager.after_event(self.events[cur.event_index])
            self.write("Whistle", cur.team, None, 50, 50, 50, 50, "", marker="period_end")
            if period == 1:
                self.first_half_len = self.sec
        self.physical.minute(int(self.t_abs // 60), self.bip_acc)
        self.manager.full_time()
