"""Find every number a piece of text claims, and check it against evidence.

Used by the Verifier, the Translator's number lock and the eval that audits cue
tracks, so all three agree on what counts as a number. Digits, decimals, percentages,
scorelines (``2-1``), ordinals (``5th``, ``1st``) and number words in English and
Spanish (``two``, ``first``, ``dos``, ``primer``) all count.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from matchlens.contracts import EvidenceItem

WORDS: dict[str, dict[str, float]] = {
    "en": {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "sixth": 6,
        "seventh": 7,
        "eighth": 8,
        "ninth": 9,
        "tenth": 10,
        "twice": 2,
        "once": 1,
        "half": 0.5,
        "double": 2,
        "treble": 3,
        "hat-trick": 3,
        "brace": 2,
    },
    "es": {
        "uno": 1,
        "dos": 2,
        "tres": 3,
        "cuatro": 4,
        "cinco": 5,
        "seis": 6,
        "siete": 7,
        "ocho": 8,
        "nueve": 9,
        "diez": 10,
        "once": 11,
        "doce": 12,
        "primer": 1,
        "primero": 1,
        "primera": 1,
        "segundo": 2,
        "segunda": 2,
        "tercer": 3,
        "tercero": 3,
        "tercera": 3,
        "cuarto": 4,
        "cuarta": 4,
        "quinto": 5,
        "quinta": 5,
        "doblete": 2,
        "triplete": 3,
    },
}
# Spanish "un" and "una" are left out: they are articles far more often than numbers.
# "second" is also a unit of time and "half" a part of the match; they are still
# claims ("second goal", "first half"), so they must be backed like any other number.
# Only the match-clock labels below are not claims.
LABELS = frozenset({"half-time", "halftime", "medio-tiempo"})

_NUMBER = re.compile(
    r"(?P<pre>xG\s)?(?<![\w.])(?P<a>\d+(?:\.\d+)?)(?:\s?[-\u2013]\s?(?P<b>\d+)(?![\d.]))?"
    r"(?P<pct>\s?%)?(?P<ord>st|nd|rd|th|º|ª|\.?º)?(?![\w])(?P<unit>\s?(?:km/h|m\b|xG\b))?"
)

UNIT_KEYS = {
    "km/h": lambda key: key.endswith("kmh"),
    "m": lambda key: key.endswith("_m"),
    "xG": lambda key: key == "xg",
}
"""Which evidence fields a number with a unit may come from: ``34.3 km/h`` must be a
speed, ``25.3 m`` a distance, ``0.27 xG`` an expected-goals value."""


@dataclass(frozen=True)
class Claim:
    """One number found in text. A scoreline is one claim with ``pair`` set."""

    text: str
    value: float
    percent: bool = False
    decimals: int = 0
    unit: str | None = None
    pair: tuple[float, float] | None = None


def extract(text: str, lang: str = "en") -> list[Claim]:
    """Every number claimed in ``text``."""
    claims: list[Claim] = []
    for m in _NUMBER.finditer(text):
        a = m.group("a")
        raw = m.group(0).strip()
        if m.group("b") is not None:
            claims.append(Claim(raw, float(a), pair=(float(a), float(m.group("b")))))
            continue
        decimals = len(a.split(".")[1]) if "." in a else 0
        unit = (m.group("unit") or "").strip() or ("xG" if m.group("pre") else None)
        claims.append(Claim(raw, float(a), bool(m.group("pct")), decimals, unit))
    words = dict(WORDS["en"])
    if lang.startswith("es"):
        words |= WORDS["es"]  # Spanish "once" is eleven, not the English adverb
    for token in re.findall(r"[^\W\d_]+(?:-[^\W\d_]+)*", text.lower()):
        if token in LABELS:
            continue
        parts = [token] if token in words else token.split("-")
        claims.extend(Claim(p, float(words[p])) for p in parts if p in words)
    return claims


def _half_up(value: float, decimals: int) -> float:
    scale = 10.0**decimals
    return float(math.floor(value * scale + 0.5)) / scale


def supports(claim: Claim, key: str, value: float) -> bool:
    """Does the evidence field ``key = value`` back this claimed number as written?

    ``34`` and ``34.3`` are both backed by 34.3 (shown to fewer places); ``44%`` and
    ``44`` by a share of 0.44. A number with a unit must come from a field of that kind.
    """
    if claim.unit and not UNIT_KEYS[claim.unit](key):
        return False
    forms = [value]
    if 0 < value <= 1:
        forms.append(value * 100)
    for f in forms:
        if claim.decimals == 0 and abs(f) < 10 and not float(f).is_integer():
            continue  # 0.71 must not back "1", nor 2.5 back "3"
        if abs(_half_up(f, claim.decimals) - claim.value) < 1e-9:
            return True
    return False


def item_supports(claim: Claim, item: EvidenceItem) -> bool:
    if claim.pair is not None:
        # A scoreline needs both goals tallies from the same fact, in either order.
        values = list(item.numbers.values())
        a, b = claim.pair
        return any(
            x == a and y == b for i, x in enumerate(values) for j, y in enumerate(values) if i != j
        )
    return any(supports(claim, k, v) for k, v in item.numbers.items())


def unsupported(text: str, evidence: list[EvidenceItem], lang: str = "en") -> list[Claim]:
    """Claims in ``text`` that no value in ``evidence`` backs."""
    return [c for c in extract(text, lang) if not any(item_supports(c, i) for i in evidence)]


def backing(claim: Claim, evidence: list[EvidenceItem]) -> list[str]:
    """Ids of the evidence items that back ``claim``."""
    return [item.id for item in evidence if item_supports(claim, item)]


def number_set(text: str, lang: str) -> list[float]:
    """The claimed values, sorted, for comparing a translation with its source."""
    values: list[float] = []
    for c in extract(text, lang):
        values += list(c.pair) if c.pair else [c.value]
    return sorted(values)
