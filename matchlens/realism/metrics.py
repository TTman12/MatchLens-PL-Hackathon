"""Every realism number, computed the same way for real and synthetic matches.

Mirrors the analyses in research/ (analyse.py, null.py, followthrough.py, leadlag.py) as one
function that returns a flat dict of named numbers.
"""

from __future__ import annotations

import random
import statistics as st
from collections.abc import Callable

from .agg import EMPTY, MatchAgg

Num = dict[str, float]


def _share(a: MatchAgg, t: str, lo: int, hi: int, k: str, minimum: int = 8) -> float | None:
    x, y = a.w(t, lo, hi, k), a.w(a.opp(t), lo, hi, k)
    return x / (x + y) if x + y >= minimum else None


def _gd(a: MatchAgg, t: str, mn: int) -> int:
    return sum(1 if g[1] == t else -1 for g in a.goals if g[0] < mn)


def _state(a: MatchAgg, t: str, mn: int) -> str:
    g = _gd(a, t, mn)
    return "losing" if g < 0 else "winning" if g > 0 else "drawing"


def _eventful(a: MatchAgg, lo: int, hi: int) -> bool:
    return any(lo <= g[0] < hi for g in a.goals) or any(lo <= r[0] < hi for r in a.reds)


def _shifts(a: MatchAgg, ft: Callable[[str, int, int], float | None], start: int = 15, end: int = 92) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    home, last = a.teams[0], -99
    for t in range(start, end):
        now, before = ft(home, t - 5, t), ft(home, t - 15, t - 5)
        if now is None or before is None:
            continue
        if abs(now - before) >= 0.30 and t - last >= 10:
            out.append((t, home if now > before else a.opp(home)))
            last = t
    return out


def _mean(v: list[float]) -> float:
    return st.mean(v) if v else float("nan")


def _median(v: list[float]) -> float:
    return st.median(v) if v else float("nan")


def compute(matches: list[MatchAgg], seed: int = 1) -> Num:
    rng = random.Random(seed)
    r: Num = {}
    n = len(matches)

    # ---- basic per-match volumes -------------------------------------------------------------
    team_rows = [(a, t) for a in matches for t in a.teams]
    passes = [a.w(t, 0, 95, "passes") for a, t in team_rows]
    acc = sum(a.w(t, 0, 95, "acc") for a, t in team_rows) / max(1, sum(passes))
    r["passes per team"] = _mean(passes)
    r["pass accuracy"] = acc
    r["duels per team"] = _mean([a.w(t, 0, 95, "duels") for a, t in team_rows])
    r["shots per team"] = _mean([a.w(t, 0, 95, "shots") for a, t in team_rows])
    r["fouls per team"] = _mean([a.w(t, 0, 95, "fouls") for a, t in team_rows])
    r["events per team"] = _mean([a.w(t, 0, 95, "events") for a, t in team_rows])
    r["final-third events per 5 min"] = _mean(
        [
            a.w(a.teams[0], t0, t0 + 5, "ft_events") + a.w(a.teams[1], t0, t0 + 5, "ft_events")
            for a in matches
            for t0 in range(0, 90, 5)
        ]
    )
    r["goals per match"] = sum(len(a.goals) for a in matches) / n
    r["reds per match"] = sum(len(a.reds) for a in matches) / n
    r["subs per team"] = sum(len(a.subs) for a in matches) / (2 * n)
    shares = [s for a in matches if (s := _share(a, a.teams[0], 0, 95, "passes")) is not None]
    r["home pass share SD across matches"] = st.pstdev(shares)
    hw = sum(1 for a in matches if _gd(a, a.teams[0], 999) > 0) / n
    dr = sum(1 for a in matches if _gd(a, a.teams[0], 999) == 0) / n
    r["home win rate"] = hw
    r["draw rate"] = dr
    acc_by = [a.w(t, 0, 95, "acc") / p for (a, t), p in zip(team_rows, passes, strict=True) if p]
    r["team pass accuracy SD"] = st.pstdev(acc_by)

    # ---- momentum shifts and their triggers ----------------------------------------------------
    def ft_of(a: MatchAgg) -> Callable[[str, int, int], float | None]:
        return lambda t, lo, hi: _share(a, t, lo, hi, "ft_events")

    def causes(a: MatchAgg, t: int, gainer: str) -> set[str]:
        c = set()
        loser = a.opp(gainer)
        for g in a.goals:
            if t - 15 <= g[0] < t:
                c.add("goal by loser" if g[1] == loser else "goal by gainer")
        for s in a.subs:
            if t - 15 <= s[1] < t:
                c.add("sub by gainer" if s[0] == gainer else "sub by loser")
        for rr in a.reds:
            if t - 15 <= rr[0] < t:
                c.add("red card")
        if 45 <= t < 60:
            c.add("half-time")
        return c

    shifts = [(a, t, g) for a in matches for t, g in _shifts(a, ft_of(a))]
    r["shifts per match"] = len(shifts) / n
    none = 0
    tally: dict[str, int] = {}
    for a, t, g in shifts:
        c = causes(a, t, g)
        none += not c
        for k in c:
            tally[k] = tally.get(k, 0) + 1
    r["shifts with no trigger"] = none / max(1, len(shifts))
    base: dict[str, int] = {}
    for _ in range(4000):
        a = rng.choice(matches)
        for k in causes(a, rng.randint(15, 91), rng.choice(a.teams)):
            base[k] = base.get(k, 0) + 1
    for k in ("sub by gainer", "half-time", "goal by loser"):
        r[f"trigger enrichment: {k}"] = (tally.get(k, 0) / max(1, len(shifts))) / max(1e-9, base.get(k, 0) / 4000)

    # noise floor: shuffle final-third events between teams at the match's average rate
    sim = 0.0
    for a in matches:
        h = [a.team.get((a.teams[0], m), EMPTY).get("ft_events", 0) for m in range(96)]
        aw = [a.team.get((a.teams[1], m), EMPTY).get("ft_events", 0) for m in range(96)]
        p = sum(h) / max(1, sum(h) + sum(aw))
        hs = [sum(rng.random() < p for _ in range(int(h[m] + aw[m]))) for m in range(96)]
        tot_ft = [h[m] + aw[m] for m in range(96)]

        def fake(t: str, lo: int, hi: int, hs: list[int] = hs, tot: list[float] = tot_ft, home: str = a.teams[0]) -> float | None:
            x, s = sum(hs[max(lo, 0) : hi]), sum(tot[max(lo, 0) : hi])
            if s < 8:
                return None
            return x / s if t == home else 1 - x / s

        sim += len(_shifts(a, fake))
    r["noise-floor shifts per match"] = sim / n

    # ---- effects of events ------------------------------------------------------------------
    def delta(a: MatchAgg, t: int, team: str, k: str, w: int = 10) -> float | None:
        x, y = _share(a, team, t - w, t, k), _share(a, team, t, t + w, k)
        return None if x is None or y is None else y - x

    d = [
        v
        for a in matches
        for g in a.goals
        if 12 <= g[0] <= 80
        and not any(0 < abs(o[0] - g[0]) <= 10 for o in a.goals)
        and not any(abs(rr[0] - g[0]) <= 10 for rr in a.reds)
        if (v := delta(a, g[0] + 1, a.opp(g[1]), "ft_events")) is not None
    ]
    r["conceding team field-tilt change"] = _median(d)
    d = [v for a in matches for rr in a.reds if 15 < rr[0] < 75 if (v := delta(a, rr[0] + 1, rr[1], "passes", 15)) is not None]
    r["red-card team pass-share change"] = _median(d)
    r["red cards measured"] = len(d)

    def sub_net(state: str) -> float:
        ds, ctrl = [], []
        for a in matches:
            for team, mn, _, _ in a.subs:
                mn = min(mn, 90)
                if 50 <= mn <= 85 and not _eventful(a, mn - 10, mn + 10) and _state(a, team, mn) == state:
                    if (v := delta(a, mn, team, "ft_events")) is not None:
                        ds.append(v)
        for _ in range(3000):
            a = rng.choice(matches)
            team, mn = rng.choice(a.teams), rng.randint(55, 80)
            if _eventful(a, mn - 10, mn + 10) or any(abs(s[1] - mn) < 12 and s[0] == team for s in a.subs):
                continue
            if _state(a, team, mn) == state and (v := delta(a, mn, team, "ft_events")) is not None:
                ctrl.append(v)
        return _mean(ds) - _mean(ctrl)

    r["sub effect when losing (net field tilt)"] = sub_net("losing")
    ins, outs = [], []
    for a in matches:
        for _, mn, pin, pout in a.subs:
            if 50 <= mn <= 80:
                outs.append(sum(a.player.get((pout, x), EMPTY).get("duels", 0) for x in range(mn - 15, mn)) / 15)
                ins.append(sum(a.player.get((pin, x), EMPTY).get("duels", 0) for x in range(mn, mn + 15)) / 15)
    r["sub duels per min vs replaced player"] = _mean(ins) / max(1e-9, _mean(outs)) - 1

    big, tot = 0, 0
    for a in matches:
        for team in a.teams:
            if _eventful(a, 35, 56):
                continue
            x, y = _share(a, team, 35, 45, "ft_events"), _share(a, team, 45, 55, "ft_events")
            if x is not None and y is not None:
                tot += 1
                big += abs(y - x) >= 0.2
    r["half-time swing >= 20 pts share"] = big / max(1, tot)

    late: dict[str, list[float]] = {"winning": [], "losing": []}
    for a in matches:
        for team in a.teams:
            st_ = _state(a, team, 75)
            if st_ in late and (v := _share(a, team, 75, 95, "ft_events")) is not None:
                late[st_].append(v)
    r["late field tilt when winning"] = _mean(late["winning"])

    # ---- per-player activity across the match ----------------------------------------------------
    subbed = {(a.match_id, s[2]) for a in matches for s in a.subs} | {(a.match_id, s[3]) for a in matches for s in a.subs}
    blocks: list[list[float]] = [[] for _ in range(6)]
    for a in matches:
        per: dict[str, list[float]] = {}
        for (pid, mn), cnt in a.player.items():
            if (a.match_id, pid) in subbed or pid in ("None", "0"):
                continue
            per.setdefault(pid, [0.0] * 6)[min(mn // 15, 5)] += cnt.get("events", 0)
        for counts in per.values():
            if sum(counts) > 20:
                for i in range(6):
                    blocks[i].append(counts[i] / 15)
    act = [_mean(b) for b in blocks]
    r["player activity 60-75 vs 0-60"] = act[4] / _mean(act[:4]) - 1

    # ---- follow-through: does an event lead to a sustained shift? -------------------------------
    def sustained(a: MatchAgg, team: str, mn: int) -> bool | None:
        x, y = _share(a, team, mn - 10, mn, "ft_events"), _share(a, team, mn + 1, mn + 11, "ft_events")
        return None if x is None or y is None else abs(y - x) >= 0.30

    def rate(v: list[bool | None]) -> float:
        k = [x for x in v if x is not None]
        return sum(k) / max(1, len(k))

    rand = [sustained(a, rng.choice(a.teams), rng.randint(15, 75)) for a in (rng.choice(matches) for _ in range(3000))]
    r["sustained shift after random minute"] = rate(rand)
    r["sustained shift after conceding"] = rate(
        [sustained(a, a.opp(g[1]), g[0] + 1) for a in matches for g in a.goals if 10 < g[0] < 78]
    )
    r["sustained shift after a sub"] = rate([sustained(a, s[0], s[1]) for a in matches for s in a.subs if 46 < s[1] < 78])

    # ---- lead-lag: the gainer is dipping before a swing ----------------------------------------
    pre, prr = [], []
    for a in matches:
        home, last = a.teams[0], -99
        for t in range(25, 86):
            now, before = _share(a, home, t, t + 5, "ft_events"), _share(a, home, t - 10, t, "ft_events")
            if now is None or before is None or abs(now - before) < 0.30 or t - last < 10:
                continue
            last = t
            g = home if now > before else a.opp(home)
            x, y = _share(a, g, t - 20, t - 10, "ft_events"), _share(a, g, t - 10, t - 5, "ft_events")
            if x is not None and y is not None:
                pre.append(y - x)
    for _ in range(4000):
        a = rng.choice(matches)
        g, t = rng.choice(a.teams), rng.randint(25, 85)
        x, y = _share(a, g, t - 20, t - 10, "ft_events"), _share(a, g, t - 10, t - 5, "ft_events")
        if x is not None and y is not None:
            prr.append(y - x)
    r["gainer pre-swing dip (SD)"] = (_mean(pre) - _mean(prr)) / max(1e-9, st.pstdev(prr))

    # ---- what play looks like during a shift ---------------------------------------------------
    def def_height(a: MatchAgg, t: str, lo: int, hi: int) -> float | None:
        n_ = a.w(t, lo, hi, "def_duels")
        return a.w(t, lo, hi, "def_x") / n_ if n_ >= 2 else None

    dh, rh = [], []
    for a, t, g in shifts:
        x, y = def_height(a, g, t - 15, t - 5), def_height(a, g, t - 5, t)
        if x is not None and y is not None:
            dh.append(y - x)
    for _ in range(3000):
        a = rng.choice(matches)
        g, t = rng.choice(a.teams), rng.randint(15, 91)
        x, y = def_height(a, g, t - 15, t - 5), def_height(a, g, t - 5, t)
        if x is not None and y is not None:
            rh.append(y - x)
    r["gainer defending height change in shift (SD)"] = (_mean(dh) - _mean(rh)) / max(1e-9, st.pstdev(rh))
    return r
