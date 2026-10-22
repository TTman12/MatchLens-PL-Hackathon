"""The Director: decides which candidate cards actually go on screen.

The Watcher and Explainer raise every candidate (about a dozen a match). A viewer wants a few
good ones, spaced out. The Director decides on the spot, as each card arrives, and never waits to
see what comes later. It puts a card up when:

- it is worth showing (`show`) and has numbers to show,
- its confidence is at least MIN_CONFIDENCE (a weak explanation never airs),
- it is at least COOLDOWN minutes after the last card on screen (a goal or red-card card may
  break the cooldown, as broadcasters do), and
- fewer than PER_HALF cards have gone up in that half.

The Watcher raises nothing before minute 15, so that is the earliest a card can go up.

When several cards arrive in the same minute, the most urgent, then most salient, is offered
first. Run over a recorded match, it makes exactly the choices it would have made live.
"""

from __future__ import annotations

from typing import Any

COOLDOWN = 10  # minutes between cards
PER_HALF = 4
MIN_CONFIDENCE = 0.45  # cards below this stay off screen


def _urgent(card: dict[str, Any]) -> bool:
    return bool(card["mode"] == "event" and card["cause"]["kind"].startswith(("red_card", "chasing", "goal_lift")))


def _half(card: dict[str, Any]) -> int:
    return 1 if card["at"] <= 47 else 2


class Director:
    """The live Director: `offer` the cards that became available in one minute, in time order."""

    def __init__(self) -> None:
        self.shown: list[dict[str, Any]] = []

    def offer(self, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Of these cards (all from the same minute), the ones that go on screen now, marked `on_screen`."""
        up = []
        for c in sorted(cards, key=lambda c: (_urgent(c), c["salience"]), reverse=True):
            if not (c["show"] and c["stats"]) or c["cause"].get("confidence", 1.0) < MIN_CONFIDENCE:
                continue
            last = self.shown[-1]["at"] if self.shown else -99
            per_half = sum(1 for s in self.shown if _half(s) == _half(c))
            if (c["at"] - last >= COOLDOWN or (_urgent(c) and c["at"] > last)) and per_half < PER_HALF:
                c["on_screen"] = True
                self.shown.append(c)
                up.append(c)
        return up


def direct(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cards to put on screen, in time order, chosen as the live Director would have chosen them.
    Each gets `on_screen: True`; the rest are untouched."""
    d = Director()
    for at in sorted({c["at"] for c in cards}):
        d.offer([c for c in cards if c["at"] == at])
    return d.shown
