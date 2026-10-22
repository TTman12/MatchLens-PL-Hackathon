"""Load the learned priors (see research/learn_priors.py) and sample from them."""

from __future__ import annotations

import bisect
import gzip
import json
import math
import random
from functools import cache
from pathlib import Path
from typing import Any

PRIORS_PATH = Path(__file__).with_name("priors.json.gz")


def zone(x: float, y: float) -> str:
    """6 x 3 grid over the 0-100 pitch in the acting team's frame (same as learn_priors.zone)."""
    return f"{min(max(int(x // (100 / 6)), 0), 5)}{min(max(int(y // (100 / 3)), 0), 2)}"


def length_bin(dx: float, dy: float) -> int:
    d = math.hypot(dx * 1.05, dy * 0.68)
    return 0 if d < 10 else 1 if d < 20 else 2 if d < 35 else 3


def dir_bin(dx: float) -> int:
    d = dx * 1.05
    return 0 if d < -5 else 2 if d > 5 else 1


class Weighted:
    """A categorical distribution with cumulative weights for fast sampling."""

    __slots__ = ("items", "cum", "total")

    def __init__(self, counts: dict[str, float]) -> None:
        self.items = list(counts)
        self.cum: list[float] = []
        total = 0.0
        for k in self.items:
            total += counts[k]
            self.cum.append(total)
        self.total = total

    def sample(self, rng: random.Random) -> str:
        return self.items[bisect.bisect_right(self.cum, rng.random() * self.total)]


class Priors:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.transitions: dict[str, dict[str, int]] = raw["transitions"]
        self.transitions_backoff: dict[str, dict[str, int]] = raw["transitions_backoff"]
        self.success: dict[str, list[int]] = raw["success"]
        self.contest: dict[str, dict[str, int]] = raw["contest"]
        self.dt: dict[str, list[float]] = raw["dt"]
        self.dt_backoff: dict[str, list[float]] = raw["dt_backoff"]
        self.roles: dict[str, dict[str, int]] = raw["roles"]
        self.opp_roles: dict[str, dict[str, int]] = raw["opp_roles"]
        self.xg_weights: list[float] = raw["xg"]["weights"]
        self.penalty_xg: float = raw["xg"]["penalty"]
        self.shot_miss = {k: Weighted(v) for k, v in raw["shot_miss"].items()}
        fouls = raw["fouls"]
        total = sum(fouls.values())
        self.card_rates = {k: v / total for k, v in fouls.items() if k != "none"}
        self.half_length = raw["half_length_s"]
        self.subs = raw["subs"]
        self._disp: dict[str, list[tuple[float, float, float]]] = {}
        self._success_backoff: dict[str, float] = {}
        agg: dict[str, list[int]] = {}
        for key, (ok, n) in self.success.items():
            typ, z, _, _ = key.split("|")
            for k in (f"{typ}|{z}", typ):
                a = agg.setdefault(k, [0, 0])
                a[0] += ok
                a[1] += n
        self._success_backoff = {k: (ok + 1) / (n + 2) for k, (ok, n) in agg.items()}

    def next_counts(self, typ: str, out: str, z: str) -> dict[str, int]:
        return (
            self.transitions.get(f"{typ}|{out}|{z}")
            or self.transitions_backoff.get(f"{typ}|{out}")
            or self.transitions_backoff.get(f"{typ}|")
            or {"Simple pass|same": 1}
        )

    def displacement(self, typ: str, z: str) -> list[tuple[float, float, float]]:
        key = f"{typ}|{z}"
        if key not in self._disp:
            raw = self.raw["displacement"].get(key)
            if raw is None:
                # fall back to the same type in the nearest populated zone
                cands = [k for k in self.raw["displacement"] if k.startswith(typ + "|")]
                raw = (
                    self.raw["displacement"][
                        min(cands, key=lambda k: abs(int(k[-2]) - int(z[0])) * 3 + abs(int(k[-1]) - int(z[1])))
                    ]
                    if cands
                    else {"0,0": 1}
                )
            self._disp[key] = [(float(k.split(",")[0]), float(k.split(",")[1]), float(c)) for k, c in raw.items()]
        return self._disp[key]

    def pass_success(self, typ: str, z: str, dx: float, dy: float) -> float:
        s = self.success.get(f"{typ}|{z}|{length_bin(dx, dy)}|{dir_bin(dx)}")
        if s is not None and s[1] >= 20:
            return (s[0] + 1) / (s[1] + 2)
        return self._success_backoff.get(f"{typ}|{z}", self._success_backoff.get(typ, 0.8))

    def contest_base(self, typ: str, z: str) -> tuple[float, float]:
        """(P(won), P(neutral)) for the perspective team in a contest."""
        c = self.contest.get(f"{typ}|{z}") or {"ok": 45, "ko": 45, "nt": 10}
        n = sum(c.values())
        return c.get("ok", 0) / n, c.get("nt", 0) / n

    def sample_dt(self, rng: random.Random, prev: str, nxt: str) -> float:
        q = self.dt.get(f"{prev}>{nxt}") or self.dt_backoff.get(prev) or [1.0] * 101
        return self.sample_quantile(rng, q)

    def sample_quantile(self, rng: random.Random, q: list[float]) -> float:
        """Sample from stored quantiles, interpolating in log space so long tails keep a realistic mean."""
        u = rng.random() * (len(q) - 1)
        i = int(u)
        a, b = math.log1p(max(q[i], 0.0)), math.log1p(max(q[min(i + 1, len(q) - 1)], 0.0))
        return math.expm1(a + (b - a) * (u - i))

    def xg(self, x: float, y: float, header: bool) -> float:
        px, py = (100 - x) * 1.05, (y - 50) * 0.68
        d = math.hypot(px, py)
        half = 7.32 / 2
        a = math.atan2(half * 2 * px, px * px + py * py - half * half) if d > 0 else math.pi
        if a < 0:
            a += math.pi
        w = self.xg_weights
        z = w[0] + w[1] * d / 10 + w[2] * a + w[3] * float(header)
        return 1 / (1 + math.exp(-z))


@cache
def load_priors(path: str | None = None) -> Priors:
    with gzip.open(path or PRIORS_PATH, "rt") as f:
        return Priors(json.load(f))
