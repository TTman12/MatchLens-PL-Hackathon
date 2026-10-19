"""Independent audit of a cue track: does every number on screen trace back to the data?

Three links are checked for every cue that carries a box (fact boxes, timeline items,
briefs), in every language:

1. **Text to box evidence.** Every number in the headline, body and analyst notes is
   backed by an evidence item attached to the box.
2. **Box evidence to moment evidence.** Every evidence item on the box is on the
   moment record with the same numbers, so a cue cannot carry a fact of its own.
3. **Moment evidence to the data.** Every evidence number is recomputed from the match
   files (events, frames, season) by the stats engine and must agree.

The audit shares only the number reader (``numbers.py``) with the Verifier; it does not
trust verdicts. Run it with ``matchlens-evals <match_dir> <out_dir>``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from matchlens.contracts import Cue, CueTrack, EvidenceItem, Moment
from matchlens.stats import StatsEngine, load_match

from .numbers import unsupported

TOLERANCE = 0.011


@dataclass
class AuditReport:
    cues_checked: int = 0
    numbers_checked: int = 0
    evidence_checked: int = 0
    problems: list[str] = field(default_factory=list)
    unchecked_sources: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        verdict = "PASS" if self.ok else f"FAIL ({len(self.problems)} problems)"
        return (
            f"{verdict}: {self.cues_checked} boxed cues, {self.numbers_checked} numbers, "
            f"{self.evidence_checked} evidence items recomputed"
        )


class Recompute:
    """Recomputes an evidence item's numbers from the match data, by its source."""

    def __init__(self, stats: StatsEngine) -> None:
        self.stats = stats
        self.match = stats.match

    def numbers(self, item: EvidenceItem, moment: Moment) -> dict[str, float] | None:
        """The numbers the data gives for ``item``'s source, or None if not recomputable."""
        src = item.source
        parts = src.split(":")
        s = self.stats
        if src in self.match.events_by_id:
            return self._event(src)
        if parts[0] == "track":
            t0, t1 = (float(x) for x in parts[2].split("-"))
            run = s.tracking.run(parts[1], t0, max(t1, moment.t_peak))
            return (
                {"top_speed_kmh": run.top_speed_kmh, "distance_m": run.distance_m} if run else None
            )
        season = self.match.season_stats.get(parts[1]) if parts[0] == "season" else None
        if (
            season is not None
            and "previous_best_kmh" not in item.numbers
            and "threshold" not in (item.numbers)
        ):
            # A Match-State lookup an agent made: the season before kick-off, as filed.
            if parts[2] == "goals" and "assists" in item.numbers:
                return {
                    "goals": season.goals,
                    "assists": season.assists,
                    "appearances": season.appearances,
                }
            if parts[2] == "yellow_cards":
                return {"yellows": season.yellow_cards}
            if parts[2] == "top_speed":
                return {"top_speed_kmh": season.top_speed_kmh or -1}
        if parts[0] == "season" and parts[2] == "goals":
            return {"goals": s.context.season_goals(parts[1], moment.t_peak)}
        if parts[0] == "season" and parts[2] == "last_goal":
            gap = s.context.matchdays_since_goal(parts[1])
            return {"matches": gap} if gap is not None else None
        if parts[0] == "season" and parts[2] == "top_speed":
            run = s.tracking.run(parts[1], *moment.replay_window)
            best = self.match.season_stats[parts[1]].top_speed_kmh
            return {
                "top_speed_kmh": run.top_speed_kmh if run else -1,
                "previous_best_kmh": best or -1,
            }
        if parts[0] == "season" and parts[2] == "yellow_cards":
            booked = [e for e in moment.involved if e.player_id == parts[1] and e.role == "fouler"]
            if not booked:
                return None
            card = booked[0].events[-1]
            d = s.context.discipline_after(card)
            return {
                "yellows": d.yellows_toward_ban,
                "threshold": d.threshold,
                "ban_matches": self.match.season.rules.ban_length_matches,
            }
        if parts[0] == "table" and parts[1] == "live":
            row = s.context.live_position(parts[2], moment.t_peak)
            return {"position": row.position, "points": row.points} if row else None
        if parts[0] == "table":
            r = s.context.table_row(parts[1])
            return {"position": r.position, "points": r.points} if r else None
        if parts[0] == "fixture":
            f = next((f for f in self.match.season.fixtures if f.match_id == parts[1]), None)
            return {"matchday": f.matchday} if f else None
        if parts[0] == "winprob":
            before = s.win_prob.at(s.win_prob.state_at(moment.t_peak, before=True))
            after = s.win_prob.at(s.win_prob.state_at(moment.t_peak + 0.01))
            out = {"home": before.home, "draw": before.draw, "away": before.away}
            sides = {(before.home, after.home), (before.away, after.away)}
            if (item.numbers.get("before"), item.numbers.get("after")) in sides:
                out |= {"before": item.numbers["before"], "after": item.numbers["after"]}
            return out
        if parts[0] == "attribution":
            a = s.attribution(parts[1])
            return {"share": a.shares.get(parts[2], -1), "touches": a.touches.get(parts[2], -1)}
        if parts[0] == "momentum":
            p = s.momentum.at(float(parts[2]))
            then = s.momentum.at(float(parts[2]) - 300.0)
            return {
                "home_threat": p.home_threat,
                "away_threat": p.away_threat,
                "momentum": p.momentum,
                "momentum_before": then.momentum,
            }
        if parts[0] == "match" and parts[2] == "touches":
            t0, t1 = (float(x) for x in parts[3].split("-"))
            n = sum(1 for e in self.match.events if e.player_id == parts[1] and t0 <= e.t <= t1)
            return {"touches": n}
        if parts[0] == "match" and parts[2] == "saves":
            n = sum(
                1
                for e in self.match.events
                if e.type == "save" and e.player_id == parts[1] and e.t <= moment.t_peak + 1.5
            )
            return {"saves": n}
        return None

    def _event(self, event_id: str) -> dict[str, float]:
        e = self.match.events_by_id[event_id]
        out: dict[str, float] = {}
        if (sq := self.stats.metrics.shot_quality(e)) is not None:
            out["xg"] = sq.xg
            if sq.shot_speed_kmh is not None:
                out["shot_speed_kmh"] = sq.shot_speed_kmh
        if e.type != "shot" and (pq := self.stats.metrics.pass_quality(e)) is not None:
            out |= {"distance_m": pq.distance_m, "difficulty": pq.difficulty}
        if e.type == "goal":
            out |= {
                "score_home": e.qualifiers.score_home or 0,
                "score_away": e.qualifiers.score_away or 0,
            }
        if e.type == "card":
            out["ban_matches"] = self.match.season.rules.ban_length_matches
        if e.type == "period_end":
            home, away = self.stats.context.score_at(e.t)
            out |= {"score_home": home, "score_away": away}
        return out


def audit(match_dir: Path | str, moments: list[Moment], track: CueTrack) -> AuditReport:
    report = AuditReport()
    stats = StatsEngine(load_match(match_dir))
    recompute = Recompute(stats)
    by_id = {m.moment_id: m for m in moments}

    for moment in moments:
        for item in moment.evidence:
            expected = recompute.numbers(item, moment)
            if expected is None:
                report.unchecked_sources.append(f"{moment.moment_id}/{item.id} {item.source}")
                continue
            report.evidence_checked += 1
            for key, value in item.numbers.items():
                if key not in expected or abs(expected[key] - value) > TOLERANCE:
                    report.problems.append(
                        f"{moment.moment_id}/{item.id} {key}={value} but the data gives "
                        f"{expected.get(key)} ({item.source})"
                    )

    for cue in track.cues:
        if cue.box is None:
            continue
        report.cues_checked += 1
        _check_cue(cue, by_id, report)
    return report


def _check_cue(cue: Cue, moments: dict[str, Moment], report: AuditReport) -> None:
    assert cue.box is not None
    box = cue.box
    texts = [box.headline, box.body] + (box.analyst.notes if box.analyst else [])
    for text in texts:
        from .numbers import extract

        report.numbers_checked += len(extract(text, cue.lang))
        for claim in unsupported(text, box.evidence, cue.lang):
            report.problems.append(
                f"{cue.cue_id} ({cue.lang}) shows '{claim.text}' with no "
                f"evidence on the box: {text!r}"
            )
    if cue.moment_id is None:
        return  # briefs carry their own evidence, recomputed below by source
    moment = moments.get(cue.moment_id)
    if moment is None:
        report.problems.append(f"{cue.cue_id} names unknown moment {cue.moment_id}")
        return
    known = {(i.id, i.source, tuple(sorted(i.numbers.items()))) for i in moment.evidence}
    for item in box.evidence:
        if (item.id, item.source, tuple(sorted(item.numbers.items()))) not in known:
            report.problems.append(
                f"{cue.cue_id} carries evidence {item.id} ({item.source}) "
                f"that is not on moment {moment.moment_id}"
            )


def audit_dir(match_dir: Path | str, out_dir: Path | str) -> AuditReport:
    out = Path(out_dir)
    moments = [
        Moment.model_validate(m)
        for m in json.loads((out / "moments.json").read_text(encoding="utf-8"))
    ]
    track = CueTrack.model_validate_json((out / "cues.json").read_text(encoding="utf-8"))
    return audit(match_dir, moments, track)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Audit a cue track against the match data.")
    parser.add_argument("match_dir")
    parser.add_argument("out_dir", help="Folder with moments.json and cues.json")
    args = parser.parse_args(argv)
    report = audit_dir(args.match_dir, args.out_dir)
    print(report.summary())
    for p in report.problems:
        print("  -", p)
    for u in report.unchecked_sources:
        print("  ? not recomputable:", u)
    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":  # pragma: no cover
    main()
