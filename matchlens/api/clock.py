"""The condensed viewer clock (build plan 3.10).

Between moments the viewer's clock runs fast; it eases down to real time a little before
every moment that matters, stays at 1x through the build-up, the replay and the fact
box, then eases back up. The speed is a pure function of match time and the moments and
cues known so far, so every viewer on the same clock sees the same thing, and a lens or
favourite-player switch never makes it jump.

``web/src/model/clock.ts`` implements the same rule for the browser.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from matchlens.agents.detector import CLOCK_SLOWDOWN_IMPORTANCE

MAX_RATE = 30.0
"""Match seconds per wall second between moments: 90 minutes in about three."""
LEAD_IN_S = 12.0
"""Match seconds of build-up played at 1x before a moment starts."""
TAIL_S = 8.0
"""Match seconds after a moment ends that stay at 1x when it has no cues yet."""
EASE_S = 20.0
"""Distance in match seconds over which the speed eases between 1x and ``MAX_RATE``."""
MERGE_GAP_S = 15.0
"""Slow stretches closer than this are joined, so the clock stays at 1x between them."""
SLOW_TEMPLATES = frozenset({"replay", "fact_box", "brief"})


@dataclass(frozen=True)
class Span:
    start: float
    end: float


def slow_spans(moments: Iterable[Any], cues: Iterable[Any]) -> list[Span]:
    """Stretches of match time that play at 1x.

    ``moments`` are ``Moment`` objects or dicts with ``moment_id``, ``t_start``, ``t_end``,
    ``replay_window`` and ``importance``; ``cues`` are ``Cue`` objects or dicts. A moment
    is slow from its lead-in to the end of its last replay or box when it has either, or
    when the detector scored it above the threshold (its cues may still be on their way,
    so it keeps a short tail). Briefs, and boxes for moments not listed, are slow too.
    """
    ends: dict[str, float] = {}
    spans: list[Span] = []
    for c in cues:
        template = str(_get(c, "template"))
        if template not in SLOW_TEMPLATES:
            continue
        t_show = float(_get(c, "t_show"))
        end = t_show + float(_get(c, "duration"))
        moment_id = _get(c, "moment_id")
        if template == "brief" or not moment_id:
            spans.append(Span(t_show - 2.0, end))
        else:
            ends[moment_id] = max(ends.get(moment_id, end), end)
            spans.append(Span(t_show - LEAD_IN_S, end))
    for m in moments:
        moment_id = str(_get(m, "moment_id"))
        if float(_get(m, "importance")) < CLOCK_SLOWDOWN_IMPORTANCE and moment_id not in ends:
            continue
        window = _get(m, "replay_window")
        start = min(float(_get(m, "t_start")), float(window[0])) - LEAD_IN_S
        spans.append(Span(start, max(float(_get(m, "t_end")) + TAIL_S, ends.get(moment_id, 0.0))))
    return merge(spans)


def merge(spans: Sequence[Span]) -> list[Span]:
    out: list[Span] = []
    for s in sorted(spans, key=lambda s: s.start):
        if out and s.start - out[-1].end < MERGE_GAP_S:
            last = out[-1]
            out[-1] = Span(last.start, max(last.end, s.end))
        else:
            out.append(s)
    return out


def rate_at(t: float, spans: Sequence[Span], max_rate: float = MAX_RATE) -> float:
    """Playback speed at match time ``t``: 1 inside a slow span, easing to ``max_rate``."""
    d = float("inf")
    for s in spans:
        if s.start <= t <= s.end:
            return 1.0
        d = min(d, abs(s.start - t), abs(t - s.end))
    x = min(1.0, d / EASE_S)
    return 1.0 + (max_rate - 1.0) * x * x * (3.0 - 2.0 * x)


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    value = getattr(obj, key, None)
    return getattr(value, "value", value)
