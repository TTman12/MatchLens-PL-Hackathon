"""Who moved the swing: the players behind each card, so the team story and the player story are one.

The Players and Substitutions specialists already find whose own output changed most since a card's
anchor. This reads their findings back for each card on screen and keeps the ones that fit the
swing: a player on the side that took over doing more ("drove"), or a player on the side that lost
it doing less ("faded"). The screen shows the top drivers as chips on the card (tap one to follow
him), tells a viewer when the player they follow is part of a swing, and adds up each player's part
in the swings for the recap.

Every number is the specialists' own: counts since the anchor, against his rate before it scaled to
the same minutes (a substitute against the player he replaced). Deterministic, so `--enrich` adds it
to existing bundles without a model call.
"""

from __future__ import annotations

from typing import Any

from .match import MatchData
from .specialists import Finding, players, substitutions
from .watcher import Moment

TOP = 3  # movers kept per card, per role
EVENT_KINDS = {"goal", "red_card", "half_time", "substitution"}
# the specialists' labels, as the chip reads them
LABELS = {"distance_m": "Metres per minute"}


def _moment(md: MatchData, card: dict[str, Any]) -> Moment:
    """The card's window again: an event's own minute holds play from before it."""
    events = [k for k in md.key_events if k.m == card["anchor_m"]] if card["kind"] in EVENT_KINDS else []
    mo = card["momentum"]
    mode = "event" if events else card["kind"]
    return Moment(card["at"], card["anchor_m"], mode, mo["gainer"], 0.0, mo["before"], mo["now"], events)


def _num(v: float) -> str:
    return f"{v:.0f}" if round(v, 1) >= 1 or v == 0 else f"{v:.1f}"


def _mover(f: Finding, role: str) -> dict[str, Any]:
    """A finding as the screen shows it: counts in the window, not rates per 10 minutes."""
    if f["metric"] == "distance_m":
        before, after = f["before"], f["after"]  # already metres per minute
    else:
        scale = f["minutes"] / 10
        before, after = f["before"] * scale, f["after"] * scale
    out = {
        "id": f["player"],
        "name": f["name"],
        "team": f["team"],
        "role": role,
        "metric": f["metric"],
        "label": LABELS.get(f["metric"], f["label"]),
        "before": _num(before),
        "after": _num(after),
        "sd": f["effect_sd"],
    }
    if f.get("replaced_name"):
        out["vs"] = f["replaced_name"]
    return out


def movers(md: MatchData, card: dict[str, Any]) -> list[dict[str, Any]]:
    """The players behind one card: drivers first, then the faded, strongest change first, one row
    per player. Empty when momentum didn't move."""
    gainer = card["momentum"].get("gainer")
    if not gainer:
        return []
    m = _moment(md, card)
    found = [f for f in players(md, m, top=TOP) if f.get("claim") == "player_change"]
    found += [f for f in substitutions(md, m) if f.get("claim") == "sub_vs_replaced"]
    best: dict[str, tuple[str, Finding]] = {}
    for f in found:
        if f["team"] == gainer and f["effect_sd"] > 0:
            role = "drove"
        elif f["team"] != gainer and f["effect_sd"] < 0:
            role = "faded"
        else:
            continue  # a player going against his side's swing doesn't explain it
        if f["player"] not in best or abs(f["effect_sd"]) > abs(best[f["player"]][1]["effect_sd"]):
            best[f["player"]] = (role, f)
    rows = [_mover(f, role) for role, f in best.values()]
    rows.sort(key=lambda r: (r["role"] != "drove", -abs(r["sd"])))
    keep = [r for r in rows if r["role"] == "drove"][:TOP] + [r for r in rows if r["role"] == "faded"][:TOP]
    return keep


def parts(cards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Player id -> his part in each swing on screen, in time order, for the recap."""
    out: dict[str, list[dict[str, Any]]] = {}
    for c in cards:
        for r in c.get("players") or []:
            row = {"at": c["at"], "clock": c["clock"], **{k: r[k] for k in ("role", "label", "before", "after")}}
            out.setdefault(r["id"], []).append(row)
    return out
