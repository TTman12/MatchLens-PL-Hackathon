"""Learn the generator's priors from the public Wyscout event data (Premier League 2017-18).

The output is aggregate probability tables only: transition counts between action types, pass
displacement histograms, success rates, timing quantiles, role shares, an xG model, card rates and
substitution timing. No event rows, match identifiers, teams or player names are written.

Data: Pappalardo et al. (2019), "A public data set of spatio-temporal match events in soccer
competitions", Scientific Data 6:236, CC BY 4.0, https://doi.org/10.6084/m9.figshare.c.4415000

Usage: python3 -I research/learn_priors.py <wyscout_dir> matchlens/gen/priors.json.gz
where <wyscout_dir> holds events_England.json, matches_England.json and players.json.
"""

from __future__ import annotations

import collections
import gzip
import json
import math
import sys
from typing import Any

PASS_TYPES = {"Simple pass", "High pass", "Head pass", "Cross", "Launch", "Smart pass", "Hand pass"}
SET_PASSES = {"Free Kick", "Free kick cross", "Corner", "Throw in", "Goal kick"}
GOAL, OWN_GOAL, ACCURATE, WON, NEUTRAL = 101, 102, 1801, 703, 702
YELLOW, RED, SECOND_YELLOW, HEADER, BLOCKED = 1702, 1701, 1703, 403, 2101
ON_TARGET = set(range(1201, 1210))
POST = set(range(1217, 1224))
QUANTILES = [i / 100 for i in range(101)]


def zone(x: float, y: float) -> str:
    """6 x 3 grid over the 0-100 pitch, in the acting team's attacking frame."""
    return f"{min(int(x // (100 / 6)), 5)}{min(int(y // (100 / 3)), 2)}"


def metres(dx: float, dy: float) -> float:
    return math.hypot(dx * 1.05, dy * 0.68)


def length_bin(dx: float, dy: float) -> int:
    d = metres(dx, dy)
    return 0 if d < 10 else 1 if d < 20 else 2 if d < 35 else 3


def dir_bin(dx: float) -> int:
    d = dx * 1.05
    return 0 if d < -5 else 2 if d > 5 else 1


def shot_category(tags: set[int]) -> str:
    if GOAL in tags:
        return "goal"
    if BLOCKED in tags:
        return "blocked"
    if tags & POST:
        return "post"
    if tags & ON_TARGET:
        return "saved"
    return "off"


def base_token(e: dict[str, Any]) -> dict[str, Any] | None:
    name, sub = e["eventName"], e["subEventName"]
    tags = {t["id"] for t in e["tags"]}
    pos = e["positions"]
    sx, sy = (pos[0]["x"], pos[0]["y"]) if pos else (50, 50)
    ex, ey = (pos[1]["x"], pos[1]["y"]) if len(pos) > 1 else (sx, sy)
    tok: dict[str, Any] = dict(
        team=e["teamId"], player=e["playerId"], t=e["eventSec"], sx=sx, sy=sy, ex=ex, ey=ey, out="", tags=tags
    )
    if name == "Pass":
        tok.update(type=sub, out="ok" if ACCURATE in tags else "ko")
    elif name == "Free Kick":
        if sub in ("Free kick shot", "Penalty"):
            tok.update(type="Penalty" if sub == "Penalty" else "Free kick shot", out=shot_category(tags))
        else:
            tok.update(type=sub, out="ok" if ACCURATE in tags else "ko")
    elif name == "Shot":
        tok.update(type="Shot", out=shot_category(tags))
    elif name == "Others on the ball":
        tok.update(type=sub)
    elif name == "Foul":
        card = "red" if RED in tags else "second_yellow" if SECOND_YELLOW in tags else "yellow" if YELLOW in tags else ""
        tok.update(type="Foul", out=card)
    elif name == "Interruption":
        tok.update(type="Ball out" if sub == "Ball out of the field" else "Whistle")
    elif name == "Offside":
        tok.update(type="Offside")
    elif name == "Save attempt":
        tok.update(type="Save")
    elif name == "Goalkeeper leaving line":
        tok.update(type="GK out")
    elif name == "Duel":
        tok.update(type="Duel:" + sub, out="ok" if WON in tags else "nt" if NEUTRAL in tags else "ko")
    else:
        return None
    return tok


def contest_type(sub: str) -> str:
    return {
        "Ground attacking duel": "Ground duel",
        "Ground defending duel": "Ground duel",
        "Ground loose ball duel": "Loose duel",
        "Air duel": "Air duel",
    }[sub]


def tokens_for_half(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise a half's events, collapsing each pair of duel events into one contest token."""
    raw = [t for t in (base_token(e) for e in events) if t is not None]
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(raw):
        a = raw[i]
        if a["type"].startswith("Duel:"):
            b = raw[i + 1] if i + 1 < len(raw) else None
            pair = b is not None and b["type"].startswith("Duel:") and b["team"] != a["team"] and abs(b["t"] - a["t"]) <= 1.5
            first = a
            if pair and b is not None and b["type"] == "Duel:Ground attacking duel":
                first = b
            other = (b if first is a else a) if pair else None
            tok = dict(first)
            tok["type"] = contest_type(first["type"][5:])
            tok["opp_player"] = other["player"] if other else None
            tok["t"] = min(a["t"], b["t"]) if pair and b is not None else a["t"]
            out.append(tok)
            i += 2 if pair else 1
            continue
        out.append(a)
        i += 1
    return out


def quantiles(values: list[float]) -> list[float]:
    v = sorted(values)
    if not v:
        return []
    return [round(v[min(int(q * (len(v) - 1)), len(v) - 1)], 3) for q in QUANTILES]


def fit_xg(rows: list[tuple[float, float, int, int]]) -> list[float]:
    """Logistic regression on (distance m, angle rad, header) by Newton's method, pure Python."""
    w = [0.0, 0.0, 0.0, 0.0]

    def feats(r: tuple[float, float, int, int]) -> list[float]:
        return [1.0, r[0] / 10, r[1], float(r[2])]

    for _ in range(25):
        g = [0.0] * 4
        h = [[0.0] * 4 for _ in range(4)]
        for r in rows:
            f = feats(r)
            z = sum(wi * fi for wi, fi in zip(w, f, strict=False))
            p = 1 / (1 + math.exp(-z))
            for i in range(4):
                g[i] += (r[3] - p) * f[i]
                for j in range(4):
                    h[i][j] -= p * (1 - p) * f[i] * f[j]
        # solve h * step = g by Gaussian elimination
        m = [row[:] + [gi] for row, gi in zip(h, g, strict=False)]
        for c in range(4):
            piv = max(range(c, 4), key=lambda r: abs(m[r][c]))
            m[c], m[piv] = m[piv], m[c]
            for r in range(4):
                if r != c:
                    k = m[r][c] / m[c][c]
                    m[r] = [a - k * b for a, b in zip(m[r], m[c], strict=False)]
        step = [m[i][4] / m[i][i] for i in range(4)]
        w = [wi - si for wi, si in zip(w, step, strict=False)]
    return [round(x, 5) for x in w]


def shot_geometry(x: float, y: float) -> tuple[float, float]:
    """Distance (m) to goal centre and the angle (rad) the goal mouth subtends, from 0-100 coords."""
    px, py = (100 - x) * 1.05, (y - 50) * 0.68
    d = math.hypot(px, py)
    half = 7.32 / 2
    a = math.atan2(half * 2 * px, px * px + py * py - half * half) if d > 0 else math.pi
    if a < 0:
        a += math.pi
    return d, a


def main(src: str, dst: str) -> None:
    events = json.load(open(f"{src}/events_England.json"))
    matches = json.load(open(f"{src}/matches_England.json"))
    roles = {p["wyId"]: p["role"]["code2"] for p in json.load(open(f"{src}/players.json"))}

    by_half: dict[tuple[int, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for e in events:
        if e["matchPeriod"] in ("1H", "2H"):
            by_half[(e["matchId"], e["matchPeriod"])].append(e)

    trans: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    trans_back: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    disp: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    success: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    contest: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    dts: dict[str, list[float]] = collections.defaultdict(list)
    dts_back: dict[str, list[float]] = collections.defaultdict(list)
    role_share: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    opp_role: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    shots: list[tuple[float, float, int, int]] = []
    miss_cat: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    fouls = collections.Counter()
    pens = [0, 0]
    half_len: dict[str, list[float]] = {"1H": [], "2H": []}
    starts = collections.Counter()

    for (_mid, period), evs in by_half.items():
        evs.sort(key=lambda e: e["eventSec"])
        half_len[period].append(evs[-1]["eventSec"])
        toks = tokens_for_half(evs)
        starts[(toks[0]["type"], round(toks[0]["sx"] / 5) * 5, round(toks[0]["sy"] / 5) * 5)] += 1
        for a, b in zip(toks, toks[1:], strict=False):
            rel = "same" if a["team"] == b["team"] else "other"
            nxt = f"{b['type']}|{rel}"
            trans[f"{a['type']}|{a['out']}|{zone(a['ex'], a['ey'])}"][nxt] += 1
            trans_back[f"{a['type']}|{a['out']}"][nxt] += 1
            dt = max(0.0, b["t"] - a["t"])
            dts[f"{a['type']}>{b['type']}"].append(dt)
            dts_back[a["type"]].append(dt)
        for a in toks:
            typ, z = a["type"], zone(a["sx"], a["sy"])
            dx, dy = a["ex"] - a["sx"], a["ey"] - a["sy"]
            role_share[f"{typ}|{z}"][roles.get(a["player"], "MD")] += 1
            if typ in PASS_TYPES or typ in SET_PASSES or typ in ("Clearance", "Acceleration", "Touch") or typ.endswith("duel"):
                disp[f"{typ}|{z}"][f"{round(dx / 2) * 2},{round(dy / 2) * 2}"] += 1
            if typ in PASS_TYPES or typ in SET_PASSES:
                s = success[f"{typ}|{z}|{length_bin(dx, dy)}|{dir_bin(dx)}"]
                s[0] += a["out"] == "ok"
                s[1] += 1
            if typ.endswith("duel"):
                contest[f"{typ}|{z}"][a["out"]] += 1
                if a.get("opp_player"):
                    opp_role[f"{typ}|{z}"][roles.get(a["opp_player"], "MD")] += 1
            if typ == "Shot":
                d, ang = shot_geometry(a["sx"], a["sy"])
                shots.append((d, ang, int(HEADER in a["tags"]), int(a["out"] == "goal")))
            if typ in ("Shot", "Free kick shot") and a["out"] != "goal":
                d, _ = shot_geometry(a["sx"], a["sy"])
                miss_cat["fk" if typ == "Free kick shot" else ("near" if d < 12 else "mid" if d < 20 else "far")][a["out"]] += 1
            if typ == "Penalty":
                pens[0] += a["out"] == "goal"
                pens[1] += 1
            if typ == "Foul":
                fouls[a["out"] or "none"] += 1

    subs: dict[str, list[int]] = collections.defaultdict(list)
    sub_counts = collections.Counter()
    for m in matches:
        for td in m["teamsData"].values():
            ss = [s for s in (td["formation"].get("substitutions") or []) if isinstance(s, dict)]
            sub_counts[len(ss)] += 1
            for i, s in enumerate(sorted(ss, key=lambda s: s["minute"])):
                subs[str(i)].append(s["minute"])

    fk_shots = [r for r in shots]
    priors = {
        "source": "Wyscout public event data, Premier League 2017-18 (Pappalardo et al. 2019, CC BY 4.0). Aggregates only.",
        "coords": "0-100 x (own goal to opponent goal) by 0-100 y, acting team's attacking frame",
        "transitions": {k: dict(v) for k, v in trans.items() if sum(v.values()) >= 30},
        "transitions_backoff": {k: dict(v) for k, v in trans_back.items()},
        "displacement": {k: dict(v) for k, v in disp.items()},
        "success": {k: v for k, v in success.items() if v[1] >= 10},
        "contest": {k: dict(v) for k, v in contest.items()},
        "dt": {k: quantiles(v) for k, v in dts.items() if len(v) >= 30},
        "dt_backoff": {k: quantiles(v) for k, v in dts_back.items()},
        "roles": {k: dict(v) for k, v in role_share.items()},
        "opp_roles": {k: dict(v) for k, v in opp_role.items()},
        "xg": {
            "weights": fit_xg(fk_shots),
            "features": ["bias", "distance_m/10", "angle_rad", "header"],
            "penalty": round(pens[0] / max(1, pens[1]), 3),
        },
        "shot_miss": {k: dict(v) for k, v in miss_cat.items()},
        "fouls": dict(fouls),
        "half_length_s": {k: quantiles(v) for k, v in half_len.items()},
        "subs": {"count": dict(sub_counts), "minute_by_order": {k: quantiles([float(x) for x in v]) for k, v in subs.items()}},
    }
    with gzip.open(dst, "wt") as f:
        json.dump(priors, f, separators=(",", ":"))
    print(
        f"halves {len(by_half)}, transition keys {len(priors['transitions'])}, shots {len(shots)}, xg {priors['xg']['weights']}"
    )
    print("fouls", dict(fouls), "pens", pens, "subs", dict(sub_counts))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
