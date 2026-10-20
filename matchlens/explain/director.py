"""The Director: decides which candidate cards actually go on screen.

The Watcher and Explainer raise every candidate (about a dozen a match). A viewer wants a few
good ones, spaced out. The Director keeps a card when:

- it is worth showing (`show`), and
- it is at least COOLDOWN minutes after the last card on screen. A goal or red-card card may
  break the cooldown, as broadcasters do.

When two candidates compete inside one cooldown, the more salient one wins. No more than
PER_HALF cards go up in a half.
"""

from __future__ import annotations

from typing import Any

COOLDOWN = 5  # minutes between cards
PER_HALF = 5


def _urgent(card: dict[str, Any]) -> bool:
    return bool(card["mode"] == "event" and card["cause"]["kind"].startswith(("red_card", "chasing", "goal_lift")))


def _half(card: dict[str, Any]) -> int:
    return 1 if card["at"] <= 47 else 2


def direct(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cards to put on screen, in time order. Each gets `on_screen: True`; the rest are untouched."""
    pool = sorted((c for c in cards if c["show"] and c["stats"]), key=lambda c: c["at"])
    chosen: list[dict[str, Any]] = []
    i = 0
    while i < len(pool):
        # every candidate that becomes available inside one cooldown competes; the best goes up
        window = [c for c in pool[i:] if c["at"] < pool[i]["at"] + COOLDOWN]
        best = max(window, key=lambda c: (_urgent(c), c["salience"]))
        last = chosen[-1]["at"] if chosen else -99
        per_half = sum(1 for c in chosen if _half(c) == _half(best))
        if (best["at"] - last >= COOLDOWN or _urgent(best)) and per_half < PER_HALF:
            chosen.append(best)
        i = pool.index(window[-1]) + 1
    for c in chosen:
        c["on_screen"] = True
    return chosen
