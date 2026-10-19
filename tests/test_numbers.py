"""The number reader shared by the Verifier, the Translator and the audit."""

from __future__ import annotations

import pytest

from matchlens.agents.numbers import extract, number_set, unsupported
from matchlens.contracts import ClaimType, EvidenceItem


def ev(**numbers: float) -> EvidenceItem:
    return EvidenceItem(id="ev1", claim_type=ClaimType.STAT, value="x", source="s", numbers=numbers)


def values(text: str, lang: str = "en") -> list[float]:
    return number_set(text, lang)


def test_reads_digits_percentages_ordinals_scores_and_words() -> None:
    assert values("34.3 km/h, 44%, 5th, 2nd, 1-0, two lines, first goal") == sorted(
        {34.3, 44, 5, 2, 1, 0}
    )
    assert values("Ya suma 7 goles, su primer gol, tres partidos", "es") == [1, 3, 7]
    assert values("a one-match ban") == [1]


def test_a_unit_written_without_a_space_keeps_its_decimals() -> None:
    # "58.8m" once read as a bare 58, which a 58.8 m distance then appeared to back.
    assert [(c.value, c.unit) for c in extract("a 58.8m run")] == [(58.8, "m")]
    assert unsupported("a 58.1m run", [ev(distance_m=58.8)])


def test_a_score_ending_a_sentence_is_still_a_score() -> None:
    assert [c.pair for c in extract("Ashmere lead 1-0.")] == [(1.0, 0.0)]


def test_a_repeated_number_is_not_a_new_one() -> None:
    assert values("1-0 up, and 1-0 it stays") == values("1-0 up")


def test_spanish_articles_are_not_numbers() -> None:
    assert values("Una ocasión de 0.18 xG, un pase", "es") == [0.18]


def test_units_must_match_the_kind_of_evidence() -> None:
    speed_and_share = [ev(top_speed_kmh=34.3, share=0.27)]
    assert not unsupported("34.3 km/h", speed_and_share)
    assert unsupported("27.0 m", speed_and_share)  # a share is not a distance
    assert not unsupported("27%", speed_and_share)


@pytest.mark.parametrize(
    ("text", "ok"),
    [("34", True), ("34.3", True), ("34.4", False), ("0.7 difficulty", True), ("1", False)],
)
def test_rounding_rules(text: str, ok: bool) -> None:
    assert (not unsupported(text, [ev(top_speed_kmh=34.3, difficulty=0.71)])) is ok


def test_scorelines_need_both_tallies_from_one_fact() -> None:
    score = ev(score_home=1, score_away=0)
    unrelated = EvidenceItem(
        id="ev2", claim_type=ClaimType.STAT, value="y", source="t", numbers={"touches": 2}
    )
    assert not unsupported("Ashmere 1-0 Brackenford", [score])
    assert unsupported("Ashmere 2-0 Brackenford", [score, unrelated])


def test_claims_carry_units() -> None:
    claims = extract("Shot at 104 km/h, xG 0.27, from 13.2 m")
    assert [c.unit for c in claims] == ["km/h", "xG", "m"]
