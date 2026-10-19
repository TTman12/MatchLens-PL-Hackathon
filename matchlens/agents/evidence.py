"""The evidence ledger: the only place numbers enter a moment.

The detector and the Match-State tools add facts here; each gets an id (``ev1``,
``ev2``, ...) unique within the moment. Agents may only state a number that one of the
facts they cite carries in ``numbers``. Named refs (``"shot"``, ``"run:ash-09"``) let
templates and prompts find a fact without knowing its id.
"""

from __future__ import annotations

from matchlens.contracts import ClaimType, EvidenceItem


def fmt(value: float) -> str:
    """A number as it is written on screen: ``104``, ``34.3``, ``0.71``."""
    if float(value).is_integer():
        return str(int(value))
    text = f"{value:.2f}".rstrip("0")
    return text


def pct(value: float) -> str:
    """A 0 to 1 probability or share as a whole percentage, without the sign."""
    return str(round(value * 100))


class EvidenceLedger:
    def __init__(self, items: list[EvidenceItem] | None = None) -> None:
        self.items: list[EvidenceItem] = list(items or [])
        self.refs: dict[str, str] = {}

    def add(
        self,
        claim_type: ClaimType,
        value: str,
        source: str,
        numbers: dict[str, float] | None = None,
        *,
        ref: str | None = None,
    ) -> str:
        """Add a fact (or return the id of an identical one) and return its id."""
        numbers = {k: float(v) for k, v in (numbers or {}).items()}
        for item in self.items:
            if item.source == source and item.value == value and item.numbers == numbers:
                if ref:
                    self.refs[ref] = item.id
                return item.id
        evidence_id = f"ev{len(self.items) + 1}"
        self.items.append(
            EvidenceItem(
                id=evidence_id, claim_type=claim_type, value=value, source=source, numbers=numbers
            )
        )
        if ref:
            self.refs[ref] = evidence_id
        return evidence_id

    def get(self, ref: str) -> EvidenceItem | None:
        evidence_id = self.refs.get(ref)
        return self.by_id(evidence_id) if evidence_id else None

    def by_id(self, evidence_id: str) -> EvidenceItem | None:
        return next((i for i in self.items if i.id == evidence_id), None)

    def ids(self, *refs: str) -> list[str]:
        """Ids for the named refs that exist, in order, without duplicates."""
        out: list[str] = []
        for ref in refs:
            evidence_id = self.refs.get(ref)
            if evidence_id and evidence_id not in out:
                out.append(evidence_id)
        return out
