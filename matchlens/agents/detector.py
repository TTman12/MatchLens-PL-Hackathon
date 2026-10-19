"""Moment Detector: deterministic rules that turn events into candidate moments.

Rules (build plan 3.5):

| Moment | Rule |
|---|---|
| goal | a ``shot`` with outcome ``goal`` |
| card | any ``card`` event |
| big_save | a saved shot with xG of at least 0.15 |
| big_chance | a missed shot (off target, blocked, post) with xG of at least 0.3 |
| corner | a ``corner`` event; the chance that won it is folded in |
| swing | momentum flips from one side to the other inside five minutes |

The detector also gathers every fact an agent may use into the moment's evidence:
speeds and distances from tracking, pass quality, xG and shot speed, contribution
shares, win probability before and after, the live table, season totals, discipline
and the next fixture.
"""

from __future__ import annotations

from dataclasses import dataclass

from matchlens.contracts import (
    ClaimType,
    EventType,
    Involvement,
    InvolvementRole,
    MatchEvent,
    Moment,
    MomentType,
    Outcome,
    WinProbability,
)
from matchlens.contracts.pitch import to_pitch
from matchlens.stats import StatsEngine
from matchlens.stats.win_probability import distance, swing

from .evidence import EvidenceLedger, fmt, pct
from .state import Contributor, MomentContext

BIG_SAVE_XG = 0.15
BIG_CHANCE_XG = 0.3
SWING_MOMENTUM = 0.5
SWING_LOOKBACK_S = 300.0
SWING_GAP_S = 600.0
SPEED_BADGE_KMH = 30.0
CLOCK_SLOWDOWN_IMPORTANCE = 0.3
"""Moments at or above this importance slow the condensed clock for every viewer."""
MAX_CONTRIBUTORS = 8

RESTARTS = frozenset(
    {
        EventType.CORNER,
        EventType.FREE_KICK,
        EventType.THROW_IN,
        EventType.GOAL_KICK,
        EventType.KICK_OFF,
    }
)

BASE_IMPORTANCE = {
    MomentType.GOAL: 0.5,
    MomentType.CARD: 0.2,
    MomentType.BIG_SAVE: 0.3,
    MomentType.BIG_CHANCE: 0.3,
    MomentType.CORNER: 0.15,
    MomentType.SWING: 0.35,
}


@dataclass
class _Candidate:
    type: MomentType
    anchor: MatchEvent
    t_start: float
    t_peak: float
    t_end: float
    replay: tuple[float, float]


class MomentDetector:
    def __init__(self, stats: StatsEngine) -> None:
        self.stats = stats
        self.match = stats.match

    # -- finding candidates ---------------------------------------------------------------

    def detect(self) -> list[MomentContext]:
        candidates = self._candidates()
        contexts = []
        for i, cand in enumerate(sorted(candidates, key=lambda c: (c.t_peak, c.type))):
            moment_id = f"{self.match.match_id}-mo{i + 1:02d}"
            contexts.append(self._build(moment_id, cand))
        return contexts

    def _candidates(self) -> list[_Candidate]:
        events = self.match.events
        out: list[_Candidate] = []
        folded: set[str] = set()
        for i, e in enumerate(events):
            if e.type is EventType.SHOT and e.outcome is Outcome.GOAL:
                attribution = self.stats.attribution(e.event_id)
                start = min(attribution.t_start, e.t - 4.0)
                out.append(
                    _Candidate(MomentType.GOAL, e, start, e.t, e.t + 0.6, (start, e.t + 0.6))
                )
            elif e.type is EventType.CARD:
                foul = self._foul_before(e)
                start = (foul.t - 3.5) if foul else e.t - 5.0
                incident = foul.t if foul else e.t
                out.append(
                    _Candidate(MomentType.CARD, e, start, e.t, e.t + 1.0, (start, incident + 1.1))
                )
            elif e.type is EventType.CORNER:
                cause = self._chance_before(i)
                start = (cause.t - 4.4) if cause else e.t - 2.0
                if cause:
                    folded.add(cause.event_id)
                follow = self._shot_after(i, 6.0)
                peak = follow.t if follow else e.t
                replay_end = (cause.t + 0.8) if cause else e.t + 3.0
                out.append(
                    _Candidate(MomentType.CORNER, e, start, peak, peak + 0.7, (start, replay_end))
                )
            elif e.type is EventType.SHOT:
                xg = self._xg(e)
                if e.outcome is Outcome.SAVED and xg >= BIG_SAVE_XG:
                    kind = MomentType.BIG_SAVE
                elif e.outcome is not Outcome.SAVED and xg >= BIG_CHANCE_XG:
                    kind = MomentType.BIG_CHANCE
                else:
                    continue
                out.append(_Candidate(kind, e, e.t - 6.0, e.t, e.t + 1.0, (e.t - 6.0, e.t + 1.0)))
        # A chance that won a corner is told as part of the corner moment.
        out = [
            c
            for c in out
            if c.type in (MomentType.CORNER, MomentType.GOAL) or c.anchor.event_id not in folded
        ]
        out.extend(self._swings())
        return out

    def _foul_before(self, card: MatchEvent) -> MatchEvent | None:
        fouls = [
            e
            for e in self.match.events
            if e.type is EventType.FOUL
            and e.player_id == card.player_id
            and 0 <= card.t - e.t <= 60
        ]
        return fouls[-1] if fouls else None

    def _chance_before(self, index: int) -> MatchEvent | None:
        corner = self.match.events[index]
        for e in reversed(self.match.events[:index]):
            if corner.t - e.t > 20:
                return None
            if e.type is EventType.SHOT and e.team_id == corner.team_id:
                return e
        return None

    def _shot_after(self, index: int, within_s: float) -> MatchEvent | None:
        corner = self.match.events[index]
        for e in self.match.events[index + 1 :]:
            if e.t - corner.t > within_s:
                return None
            if e.type is EventType.SHOT and e.team_id == corner.team_id:
                return e
        return None

    def _swings(self) -> list[_Candidate]:
        out: list[_Candidate] = []
        last = -SWING_GAP_S
        for e in self.match.events:
            if e.team_id is None or e.t - last < SWING_GAP_S or e.t < SWING_LOOKBACK_S:
                continue
            now = self.stats.momentum.at(e.t).momentum
            then = self.stats.momentum.at(e.t - SWING_LOOKBACK_S).momentum
            if abs(now) >= SWING_MOMENTUM and abs(then) >= SWING_MOMENTUM and now * then < 0:
                out.append(_Candidate(MomentType.SWING, e, e.t - 20, e.t, e.t, (e.t - 20, e.t)))
                last = e.t
        return out

    def _xg(self, shot: MatchEvent) -> float:
        quality = self.stats.metrics.shot_quality(shot)
        return quality.xg if quality else 0.0

    # -- building the moment record -------------------------------------------------------

    def _build(self, moment_id: str, cand: _Candidate) -> MomentContext:
        wp = self.stats.win_prob
        before_state = wp.state_at(cand.t_peak, before=True)
        after_state = wp.state_at(cand.t_peak + 0.01)
        before, after = wp.at(before_state), wp.at(after_state)
        ledger = EvidenceLedger()
        ctx = MomentContext(
            moment=Moment(
                moment_id=moment_id,
                match_id=self.match.match_id,
                type=cand.type,
                period=cand.anchor.period,
                t_start=round(cand.t_start, 1),
                t_peak=round(cand.t_peak, 1),
                t_end=round(cand.t_end, 1),
                replay_window=(round(cand.replay[0], 1), round(cand.replay[1], 1)),
                importance=0.0,
                win_prob_before=before,
                win_prob_after=after,
                swing=swing(before, after),
            ),
            ledger=ledger,
            surprise=round(distance(before, after), 3),
            suspense=wp.suspense(before_state),
        )
        ctx.names = {pid: p.short_name for pid, p in self.match.players.items()}
        ctx.names |= {tid: c.short_name for tid, c in self.match.clubs.items()}
        ctx.facts |= {
            "derby": self.match.meta.stakes.derby,
            "home_id": self.match.home_id,
            "away_id": self.match.away_id,
        }
        builders = {
            MomentType.GOAL: self._goal,
            MomentType.CARD: self._card,
            MomentType.CORNER: self._corner,
            MomentType.BIG_SAVE: self._shot_moment,
            MomentType.BIG_CHANCE: self._shot_moment,
            MomentType.SWING: self._swing,
        }
        builders[cand.type](ctx, cand)
        self._add_runs(ctx)
        self._win_prob_evidence(ctx, before, after)
        ctx.moment.importance = self._importance(ctx)
        ctx.moment.involved = [
            Involvement(
                player_id=c.player_id,
                role=InvolvementRole(c.role),
                events=c.events,
                touches=c.touches,
                top_speed_kmh=c.run.top_speed_kmh if c.run else None,
                distance_in_window_m=c.run.distance_m if c.run else None,
            )
            for c in ctx.contributors
        ]
        ctx.moment.context_refs = sorted(
            {
                i.source
                for i in ledger.items
                if ":" in i.source and not i.source.startswith(("track:", "winprob:"))
            }
        )
        ctx.event_ids = sorted({eid for c in ctx.contributors for eid in c.events})
        ctx.sync()
        return ctx

    def _importance(self, ctx: MomentContext) -> float:
        m = ctx.moment
        score = BASE_IMPORTANCE[m.type] + 1.0 * ctx.surprise + 0.5 * ctx.suspense
        if m.type in (MomentType.BIG_SAVE, MomentType.BIG_CHANCE):
            score += 0.4 * float(ctx.facts.get("xg", 0.0))
        if ctx.facts.get("banned"):
            score += 0.3
        if self.match.meta.stakes.derby:
            score += 0.03
        return round(min(1.0, score), 2)

    def _win_prob_evidence(
        self, ctx: MomentContext, before: WinProbability, after: WinProbability
    ) -> None:
        home = self.match.club_name(self.match.home_id)
        away = self.match.club_name(self.match.away_id)
        source = f"winprob:{self.match.match_id}:{fmt(ctx.moment.t_peak)}"
        if ctx.moment.swing == 0 and ctx.surprise == 0:
            ctx.ledger.add(
                ClaimType.WIN_PROB,
                f"{home} win probability {pct(before.home)}%, {away} {pct(before.away)}%",
                source,
                {"home": before.home, "draw": before.draw, "away": before.away},
                ref="win_prob",
            )
            return
        for team_id, b, a in (
            (self.match.home_id, before.home, after.home),
            (self.match.away_id, before.away, after.away),
        ):
            ctx.ledger.add(
                ClaimType.WIN_PROB,
                f"{self.match.club_name(team_id)} win probability {pct(b)}% to {pct(a)}%",
                source,
                {"before": b, "after": a},
                ref=f"win_prob:{team_id}",
            )

    def _add_runs(self, ctx: MomentContext) -> None:
        t0, t1 = ctx.moment.replay_window
        for c in ctx.contributors:
            c.run = self.stats.tracking.run(c.player_id, t0, max(t1, ctx.moment.t_peak))
            if c.run is None:
                continue
            name = ctx.names.get(c.player_id, c.player_id)
            ctx.ledger.add(
                ClaimType.STAT,
                f"{name} reached {fmt(c.run.top_speed_kmh)} km/h, "
                f"covering {fmt(c.run.distance_m)} m",
                f"track:{c.player_id}:{fmt(t0)}-{fmt(t1)}",
                {"top_speed_kmh": c.run.top_speed_kmh, "distance_m": c.run.distance_m},
                ref=f"run:{c.player_id}",
            )
            best = self.match.season_stats.get(c.player_id)
            if best and best.top_speed_kmh and c.run.top_speed_kmh > best.top_speed_kmh:
                ctx.ledger.add(
                    ClaimType.SEASON,
                    f"{name}'s fastest this season, beating {fmt(best.top_speed_kmh)} km/h",
                    f"season:{c.player_id}:top_speed",
                    {"top_speed_kmh": c.run.top_speed_kmh, "previous_best_kmh": best.top_speed_kmh},
                    ref=f"season_best:{c.player_id}",
                )

    def _shot_evidence(self, ctx: MomentContext, shot: MatchEvent, ref: str = "shot") -> None:
        quality = self.stats.metrics.shot_quality(shot)
        if quality is None:
            return
        numbers = {"xg": quality.xg}
        text = f"xG {fmt(quality.xg)}"
        if quality.shot_speed_kmh is not None:
            numbers["shot_speed_kmh"] = quality.shot_speed_kmh
            text = f"Shot at {fmt(quality.shot_speed_kmh)} km/h, {text}"
        ctx.ledger.add(ClaimType.STAT, text, shot.event_id, numbers, ref=ref)
        ctx.facts["xg"] = quality.xg
        ctx.facts["body_part"] = shot.qualifiers.body_part

    def _pass_evidence(self, ctx: MomentContext, event: MatchEvent, ref: str) -> None:
        pq = self.stats.metrics.pass_quality(event)
        if pq is None:
            return
        kind = event.qualifiers.pass_type or "pass"
        label = {
            "through": "through ball",
            "cross": "cross",
            "lofted": "lofted ball",
            "long": "long ball",
            "cut_back": "cut-back",
        }.get(kind, "pass")
        broke = "line-breaking " if pq.line_breaking else ""
        ctx.ledger.add(
            ClaimType.STAT,
            f"{fmt(pq.distance_m)} m {broke}{label}, difficulty {fmt(pq.difficulty)}",
            event.event_id,
            {"distance_m": pq.distance_m, "difficulty": pq.difficulty},
            ref=ref,
        )
        ctx.facts[f"{ref}:line_breaking"] = pq.line_breaking
        ctx.facts[f"{ref}:pass_type"] = kind
        ctx.facts[f"{ref}:pressure"] = pq.pressure_on_passer
        if event.start and event.end and event.team_id:
            d = self.stats.metrics.direction(event.team_id, event.period)
            a, b = to_pitch(event.start, d), to_pitch(event.end, d)
            ctx.pass_map.append((round(a[0], 1), round(a[1], 1), round(b[0], 1), round(b[1], 1)))

    # -- per moment type ------------------------------------------------------------------

    def _goal(self, ctx: MomentContext, cand: _Candidate) -> None:
        shot = cand.anchor
        assert shot.player_id is not None and shot.team_id is not None
        goal = next(
            (e for e in self.match.events if e.type is EventType.GOAL and e.t == shot.t), None
        )
        scorer = goal.player_id if goal and goal.player_id else shot.player_id
        assist = goal.qualifiers.assist_player_id if goal else None
        ctx.moment.scoring_team = shot.team_id
        attribution = self.stats.attribution(shot.event_id)
        events = {e.event_id: e for e in self.match.events}

        ranked = attribution.ranked()
        for pid, share in ranked:
            touches = attribution.touches.get(pid, 0)
            if pid == scorer:
                role = "scorer"
            elif pid == assist:
                role = "assist"
            elif share >= 0.05 or touches >= 2:
                role = "build_up"
            else:
                continue
            ctx.contributors.append(
                Contributor(pid, role, attribution.events.get(pid, []), touches, share)
            )
        if assist and not ctx.contributor(assist):
            ctx.contributors.append(Contributor(assist, "assist", [], 0, 0.0))
        order = {"scorer": 0, "assist": 1, "build_up": 2}
        ctx.contributors.sort(key=lambda c: (order[c.role], -(c.share or 0), c.player_id))
        ctx.contributors = ctx.contributors[:MAX_CONTRIBUTORS]

        self._shot_evidence(ctx, shot)
        for c in ctx.contributors:
            name = ctx.names.get(c.player_id, c.player_id)
            for eid in c.events:
                e = events[eid]
                pq = self.stats.metrics.pass_quality(e) if e.type is EventType.PASS else None
                is_key = e.receiver_id == scorer and e.outcome is Outcome.COMPLETE
                if pq and (is_key or pq.line_breaking or pq.difficulty >= 0.6):
                    self._pass_evidence(ctx, e, f"pass:{c.player_id}")
            if c.share is not None:
                ctx.ledger.add(
                    ClaimType.STAT,
                    f"{name}: {c.touches} touches in the move, {pct(c.share)}% of its value",
                    f"attribution:{shot.event_id}:{c.player_id}",
                    {"touches": c.touches, "share": c.share},
                    ref=f"share:{c.player_id}",
                )

        assert goal is not None
        hs, as_ = goal.qualifiers.score_home or 0, goal.qualifiers.score_away or 0
        home, away = (
            self.match.club_name(self.match.home_id),
            self.match.club_name(self.match.away_id),
        )
        ctx.ledger.add(
            ClaimType.STAT,
            f"{home} {hs}-{as_} {away}",
            goal.event_id,
            {"score_home": hs, "score_away": as_},
            ref="score",
        )
        ctx.facts |= {"scorer": scorer, "assist": assist, "score": (hs, as_)}

        season = self.stats.context
        goals = season.season_goals(scorer, shot.t)
        scorer_name = ctx.names.get(scorer, scorer)
        ctx.ledger.add(
            ClaimType.SEASON,
            f"{scorer_name} now has {goals} league goals this season",
            f"season:{scorer}:goals",
            {"goals": goals},
            ref="season_goals",
        )
        gap = season.matchdays_since_goal(scorer)
        if goals == 1:
            ctx.ledger.add(
                ClaimType.MILESTONE,
                f"{scorer_name}'s first league goal this season",
                f"season:{scorer}:goals",
                {"goals": 1},
                ref="milestone",
            )
        elif gap is not None and gap >= 3:
            ctx.ledger.add(
                ClaimType.MILESTONE,
                f"{scorer_name}'s first goal in {gap} matches",
                f"season:{scorer}:last_goal",
                {"matches": gap},
                ref="milestone",
            )
        self._table_evidence(ctx, shot.t)

    def _table_evidence(self, ctx: MomentContext, t: float) -> None:
        c = self.stats.context
        for team_id in (self.match.home_id, self.match.away_id):
            name = self.match.club_name(team_id)
            row = c.table_row(team_id)
            live = c.live_position(team_id, t)
            if row:
                ctx.ledger.add(
                    ClaimType.TABLE,
                    f"{name} started the day {_ordinal(row.position)} on {row.points} points",
                    f"table:{team_id}",
                    {"position": row.position, "points": row.points},
                    ref=f"table:{team_id}",
                )
            if live:
                ctx.ledger.add(
                    ClaimType.TABLE,
                    f"{name} {_ordinal(live.position)} on the live table, {live.points} points",
                    f"table:live:{team_id}",
                    {"position": live.position, "points": live.points},
                    ref=f"live:{team_id}",
                )
                ctx.facts[f"moved:{team_id}"] = bool(row and row.position != live.position)
                ctx.facts[f"live_position:{team_id}"] = live.position

    def _card(self, ctx: MomentContext, cand: _Candidate) -> None:
        card = cand.anchor
        assert card.player_id is not None and card.team_id is not None
        foul = self._foul_before(card)
        name = ctx.names.get(card.player_id, card.player_id)
        ctx.contributors.append(
            Contributor(card.player_id, "fouler", [x.event_id for x in (foul, card) if x], 1)
        )
        if foul and foul.related_player_id:
            victim_events = [
                e.event_id
                for e in self.match.events
                if e.player_id == foul.related_player_id and cand.t_start <= e.t <= foul.t
            ]
            ctx.contributors.append(
                Contributor(foul.related_player_id, "fouled", victim_events, len(victim_events))
            )
        discipline = self.stats.context.discipline_after(card.event_id)
        red = card.outcome in (Outcome.RED, Outcome.SECOND_YELLOW)
        ctx.facts |= {
            "card": str(card.outcome),
            "red": red,
            "banned": discipline.banned,
            "booked": card.player_id,
            "booked_team": card.team_id,
        }
        if red:
            ctx.ledger.add(
                ClaimType.DISCIPLINE,
                f"{name} sent off, banned for the next match",
                card.event_id,
                {"ban_matches": self.match.season.rules.ban_length_matches},
                ref="discipline",
            )
        else:
            ctx.ledger.add(
                ClaimType.DISCIPLINE,
                f"{name}'s yellow card number {discipline.yellows_toward_ban}; "
                f"{discipline.threshold} brings a one-match ban",
                f"season:{card.player_id}:yellow_cards",
                {
                    "yellows": discipline.yellows_toward_ban,
                    "threshold": discipline.threshold,
                    "ban_matches": self.match.season.rules.ban_length_matches,
                },
                ref="discipline",
            )
        fixture = discipline.banned_for
        if fixture is not None:
            opponent = fixture.away_id if fixture.home_id == card.team_id else fixture.home_id
            venue = "home to" if fixture.home_id == card.team_id else "away at"
            ctx.ledger.add(
                ClaimType.FIXTURE,
                f"Next match: {venue} {self.match.club_name(opponent)}, "
                f"matchday {fixture.matchday}",
                f"fixture:{fixture.match_id}",
                {"matchday": fixture.matchday},
                ref="fixture",
            )
            ctx.facts |= {
                "ban_opponent": opponent,
                "ban_venue": "home" if venue == "home to" else "away",
            }
        if foul and foul.qualifiers.severity is not None:
            ctx.facts["severity"] = foul.qualifiers.severity
        if red:
            self._table_evidence(ctx, card.t)

    def _corner(self, ctx: MomentContext, cand: _Candidate) -> None:
        corner = cand.anchor
        assert corner.player_id is not None
        index = self.match.events.index(corner)
        cause = self._chance_before(index)
        if cause and cause.player_id:
            ctx.contributors.append(Contributor(cause.player_id, "shooter", [cause.event_id], 1))
            self._shot_evidence(ctx, cause, ref="won_by")
        ctx.contributors.append(Contributor(corner.player_id, "taker", [corner.event_id], 1))
        follow = self._shot_after(index, 6.0)
        if follow and follow.player_id:
            if not ctx.contributor(follow.player_id):
                ctx.contributors.append(
                    Contributor(follow.player_id, "shooter", [follow.event_id], 1)
                )
            self._shot_evidence(ctx, follow, ref="shot")
            ctx.facts["corner_shot_outcome"] = str(follow.outcome)
        ctx.facts["team"] = corner.team_id

    def _shot_moment(self, ctx: MomentContext, cand: _Candidate) -> None:
        shot = cand.anchor
        assert shot.player_id is not None
        ctx.contributors.append(Contributor(shot.player_id, "shooter", [shot.event_id], 1))
        self._shot_evidence(ctx, shot)
        ctx.facts |= {"team": shot.team_id, "outcome": str(shot.outcome)}
        save = next(
            (e for e in self.match.events if e.type is EventType.SAVE and 0 <= e.t - shot.t <= 1.5),
            None,
        )
        if save and save.player_id:
            ctx.contributors.append(Contributor(save.player_id, "keeper", [save.event_id], 1))
            saves = sum(
                1
                for e in self.match.events
                if e.type is EventType.SAVE and e.player_id == save.player_id and e.t <= save.t
            )
            ctx.ledger.add(
                ClaimType.STAT,
                f"{ctx.names.get(save.player_id)}'s save number {saves} today",
                f"match:{save.player_id}:saves",
                {"saves": saves},
                ref="saves",
            )

    def _swing(self, ctx: MomentContext, cand: _Candidate) -> None:
        now = self.stats.momentum.at(cand.t_peak)
        then = self.stats.momentum.at(cand.t_peak - SWING_LOOKBACK_S)
        team = self.match.home_id if now.momentum > 0 else self.match.away_id
        ctx.facts |= {"team": team}
        ctx.ledger.add(
            ClaimType.STAT,
            f"Threat points over five minutes: {self.match.club_name(self.match.home_id)} "
            f"{fmt(now.home_threat)}, {self.match.club_name(self.match.away_id)} "
            f"{fmt(now.away_threat)}",
            f"momentum:{self.match.match_id}:{fmt(cand.t_peak)}",
            {
                "home_threat": now.home_threat,
                "away_threat": now.away_threat,
                "momentum": now.momentum,
                "momentum_before": then.momentum,
            },
            ref="momentum",
        )
        recent = [
            e
            for e in self.match.events
            if e.team_id == team and e.player_id and cand.t_peak - 60 <= e.t <= cand.t_peak
        ]
        seen: dict[str, list[str]] = {}
        for e in recent:
            assert e.player_id is not None
            seen.setdefault(e.player_id, []).append(e.event_id)
        for pid, eids in sorted(seen.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:3]:
            if len(eids) >= 2:
                ctx.contributors.append(Contributor(pid, "build_up", eids, len(eids)))
                ctx.ledger.add(
                    ClaimType.STAT,
                    f"{ctx.names.get(pid, pid)}: {len(eids)} touches in the last minute",
                    f"match:{pid}:touches:{fmt(cand.t_peak - 60)}-{fmt(cand.t_peak)}",
                    {"touches": len(eids)},
                    ref=f"touches:{pid}",
                )


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def detect_moments(stats: StatsEngine) -> list[MomentContext]:
    return MomentDetector(stats).detect()
