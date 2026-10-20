"""The findings board: the shared state the agents work from.

Every specialist's tool posts its findings here, each under an id (F1, F2, ...), so the other
agents can refer to a number without ever retyping it. The Explainer chooses ids; the card is
built from the board, so a number on screen is always the one a tool computed.

One record per finding, as in docs/design.md section 5:

    {id, agent, claim_type, metric, label, team, player?, before, after, unit, effect_sd, evidence_ids}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..explain.explainer import OFF_SCREEN, _visible
from ..explain.specialists import Finding

SPECIALISTS = ("team_play", "players", "substitutions", "match_events")
VIEW_LIMIT = 16  # stat findings shown to the Explainer, largest effect first


def is_stat(f: Finding) -> bool:
    """A finding with a before/after number that could go on screen."""
    return "before" in f and "after" in f and "unit" in f


def eligible(f: Finding) -> bool:
    """Worth offering for the screen: a team stat that clearly moved, or a player finding (a sub, a fade)."""
    if not is_stat(f):
        return False
    if f["agent"] == "team_play":
        return f["metric"] not in OFF_SCREEN and _visible(f) and abs(f["effect_sd"]) >= 1.0
    return f["claim"] in ("sub_vs_replaced", "fatigue")


@dataclass
class Board:
    findings: dict[str, Finding] = field(default_factory=dict)
    notes: dict[str, dict[str, Any]] = field(default_factory=dict)  # each specialist's verdict

    def post(self, agent: str, found: list[Finding]) -> list[str]:
        ids = []
        for f in found:
            fid = f"F{len(self.findings) + 1}"
            self.findings[fid] = f
            ids.append(fid)
        return ids

    def note(self, agent: str, verdict: str, highlights: list[str], text: str) -> None:
        self.notes[agent] = {
            "verdict": verdict,
            "highlights": [h for h in highlights if h in self.findings],
            "note": text[:120],
        }

    def id_of(self, f: Finding) -> str | None:
        return next((k for k, v in self.findings.items() if v is f), None)

    def by_agent(self) -> dict[str, list[Finding]]:
        """The board in the shape the deterministic specialists return, for the Verifier and fallback."""
        out: dict[str, list[Finding]] = {a: [] for a in SPECIALISTS}
        for f in self.findings.values():
            out.setdefault(f["agent"], []).append(f)
        return out

    def view(self, fids: list[str] | None = None, limit: int = VIEW_LIMIT) -> list[dict[str, Any]]:
        """Compact records for a prompt. Without `fids`: the eligible stats plus match context."""
        if fids is None:
            stats = [k for k, f in self.findings.items() if eligible(f)]
            stats.sort(key=lambda k: -abs(self.findings[k]["effect_sd"]))
            context = [k for k, f in self.findings.items() if f["agent"] == "match_events"]
            fids = stats[:limit] + context
        return [record(k, self.findings[k], self.highlighted(k)) for k in fids]

    def highlighted(self, fid: str) -> bool:
        return any(fid in n["highlights"] for n in self.notes.values())


def record(fid: str, f: Finding, highlighted: bool = False) -> dict[str, Any]:
    r: dict[str, Any] = {"id": fid, "agent": f["agent"], "claim_type": f["claim"], "team": f["team"]}
    for k in ("name", "replaced_name", "metric", "label", "before", "after", "unit", "effect_sd", "minutes"):
        if f.get(k) is not None:
            r[k] = f[k]
    for k in ("state", "goal_diff", "goal_diff_at_anchor", "players_on", "clock", "players"):
        if k in f:
            r[k] = f[k]
    if f.get("evidence"):
        r["evidence_ids"] = f["evidence"]
    if f["agent"] == "team_play":
        r["polarity"] = f.get("polarity", 0)  # +1: more of this means more control for that team
    if highlighted:
        r["highlighted"] = True
    return r
