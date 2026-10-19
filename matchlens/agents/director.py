"""The Director: attention budget, camera, replay scheduling and timing.

Rules (build plan 3.6 and 3.7):

- **One box on screen at a time** per track, for about 8 seconds.
- **Per track, at most 8 boxes per half**, with **at least 4 match minutes** between
  boxes. Goals and red cards break the cooldown. A track is one lens view: each
  player's Player-lens track, each club's Club-lens track, and the Pundit track. So a
  fan of a quiet midfielder is never starved because the striker used the budget.
- **Priority = importance x relevance.** Below 0.3, or out of budget, or in cooldown,
  the moment goes to the **timeline rail** instead of the screen. Nothing is lost.
- **A card with no suspension gets no box**: it goes to the timeline.
- **Replays live in dead time.** A goal replays straight after the goal; anything else
  waits for the next stoppage (a restart with no open play before it) within 20 match
  seconds, or is not replayed. The box follows the replay.
- **Camera** per moment type: spider-cam for goals, low corner angle, card close-up,
  reverse angle for saves, high tactical cam for chances and swings.
- **Speed badges** pop when a contributor tops 30 km/h or beats their season best.
- **Every moment gets a line on the global timeline rail**, whatever the lenses decided.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from matchlens.contracts import (
    AnalystDetail,
    CameraShot,
    DirectorDecision,
    EventType,
    FactBox,
    Layer,
    MomentStatus,
    MomentType,
    Template,
)
from matchlens.stats import StatsEngine

from . import templates
from .detector import RESTARTS, SPEED_BADGE_KMH
from .state import MomentContext, VerifiedMoment
from .trace import AgentTrace

CAMERA = {
    MomentType.GOAL: CameraShot.SPIDERCAM_GOAL,
    MomentType.CORNER: CameraShot.CORNER_LOW,
    MomentType.CARD: CameraShot.CARD_CLOSE,
    MomentType.BIG_SAVE: CameraShot.SAVE_REVERSE,
    MomentType.BIG_CHANCE: CameraShot.TACTICAL_HIGH,
    MomentType.SWING: CameraShot.TACTICAL_HIGH,
}

RELEVANCE = {
    "scorer": 1.0,
    "assist": 1.0,
    "keeper": 1.0,
    "shooter": 0.9,
    "fouler": 1.0,
    "build_up": 0.85,
    "fouled": 0.6,
    "taker": 0.5,
    "defender": 0.7,
}

OPEN_PLAY = frozenset(
    {
        EventType.PASS,
        EventType.CARRY,
        EventType.SHOT,
        EventType.TACKLE,
        EventType.INTERCEPTION,
        EventType.PRESSURE,
    }
)


@dataclass
class DirectorConfig:
    boxes_per_half: int = 8
    cooldown_s: float = 240.0
    box_duration_s: float = 8.0
    timeline_duration_s: float = 6.0
    min_priority: float = 0.3
    replay_speed: float = 0.5
    max_replay_s: float = 24.0
    min_replay_s: float = 4.0
    stoppage_wait_s: float = 20.0
    goal_replay_delay_s: float = 2.0


@dataclass
class _Track:
    used: dict[int, int] = field(default_factory=dict)
    last_box_t: float | None = None
    busy_until: float = 0.0


class Director:
    def __init__(
        self, stats: StatsEngine, trace: AgentTrace, config: DirectorConfig | None = None
    ) -> None:
        self.stats = stats
        self.match = stats.match
        self.trace = trace
        self.config = config or DirectorConfig()
        self.tracks: dict[str, _Track] = {}

    # -- replay timing --------------------------------------------------------------------

    def replay_slot(self, ctx: MomentContext) -> tuple[float, float] | None:
        """(start, playback seconds) for the replay, or None if there is no dead time."""
        m, c = ctx.moment, self.config
        window = m.replay_window[1] - m.replay_window[0]
        wanted = min(window / c.replay_speed, c.max_replay_s)
        if m.type is MomentType.GOAL:
            start = m.t_peak + c.goal_replay_delay_s
            restart = next(
                (e.t for e in self.match.events if e.type is EventType.KICK_OFF and e.t > m.t_peak),
                start + wanted,
            )
            length = min(wanted, restart - start - 1.0)
            return (round(start, 1), round(length, 1)) if length >= c.min_replay_s else None
        for e in self.match.events:
            if e.t <= m.t_end:
                continue
            if e.t - m.t_end > c.stoppage_wait_s:
                return None
            if e.type in OPEN_PLAY:
                return None
            if e.type in RESTARTS:
                start = m.t_end + 1.0
                length = min(wanted, e.t - start)
                if length < c.min_replay_s:
                    return None
                return round(start, 1), round(length, 1)
        return None

    # -- the budget -----------------------------------------------------------------------

    def _relevance(self, ctx: MomentContext, key: str) -> float:
        kind, _, subject = key.partition(":")
        if kind == "player":
            c = ctx.contributor(subject)
            return RELEVANCE.get(c.role, 0.7) if c else 0.5
        if kind == "club":
            return 1.0
        return 0.9

    def _decide(self, ctx: MomentContext, key: str, priority: float) -> tuple[bool, str]:
        m, c = ctx.moment, self.config
        track = self.tracks.setdefault(key, _Track())
        # Goals and red cards break the cooldown (build plan 3.6). So does a suspension:
        # it is rare, and "out for the next match" is the Club lens's core story.
        breaks_cooldown = m.type is MomentType.GOAL or bool(
            ctx.facts.get("red") or ctx.facts.get("banned")
        )
        if m.type is MomentType.CARD and not ctx.facts.get("banned") and not ctx.facts.get("red"):
            return False, "card with no suspension: timeline only"
        if priority < c.min_priority:
            return False, f"priority {priority:.2f} below {c.min_priority}: timeline"
        if track.used.get(m.period, 0) >= c.boxes_per_half:
            return False, "no boxes left this half: timeline"
        if (
            track.last_box_t is not None
            and m.t_peak - track.last_box_t < c.cooldown_s
            and not breaks_cooldown
        ):
            return False, "inside the 4-minute cooldown: timeline"
        return True, "on screen"

    # -- scheduling -----------------------------------------------------------------------

    def schedule(self, vm: VerifiedMoment) -> list[dict[str, Any]]:
        ctx = vm.ctx
        m, c = ctx.moment, self.config
        camera = CAMERA[m.type]
        slot = self.replay_slot(ctx)
        cues: list[dict[str, Any]] = []
        base = {"match_id": m.match_id, "moment_id": m.moment_id, "lang": "en"}
        if slot:
            replay_at, length = slot
            box_at = replay_at + length
            cues.append(
                base
                | {
                    "t_show": replay_at,
                    "duration": length,
                    "layer": Layer.GLOBAL,
                    "template": Template.REPLAY,
                    "priority": m.importance,
                    "camera": {
                        "shot": camera,
                        "replay": m.replay_window,
                        "replay_speed": c.replay_speed,
                    },
                }
            )
            for contributor in ctx.contributors:
                run = contributor.run
                cues.append(
                    base
                    | {
                        "t_show": replay_at,
                        "duration": length,
                        "layer": Layer.PLAYER,
                        "template": Template.REPLAY,
                        "player_id": contributor.player_id,
                        "priority": m.importance,
                        "camera": {
                            "shot": camera,
                            "replay": m.replay_window,
                            "replay_speed": c.replay_speed,
                            "highlight": contributor.player_id,
                            "trail": True,
                            "speedo": run.top_speed_kmh if run else None,
                        },
                    }
                )
        else:
            replay_at, box_at = None, m.t_end + 1.0
        cues.extend(self._speed_badges(ctx, base))
        rail = templates.timeline_template(ctx)
        headline, body = templates.render(rail, "en")
        cues.append(
            base
            | {
                "_key": "rail",
                "_template": rail,
                "t_show": round(m.t_peak + 1.0, 1),
                "duration": c.timeline_duration_s,
                "layer": Layer.GLOBAL,
                "template": Template.TIMELINE_ITEM,
                "priority": m.importance,
                "box": self._box(ctx, headline, body, rail.evidence_ids, "timeline"),
            }
        )

        show: list[str] = []
        budget_left: dict[str, int] = {}
        for key, result in sorted(vm.results.items()):
            draft = result.draft
            priority = round(m.importance * self._relevance(ctx, key), 2)
            on_screen, reason = self._decide(ctx, key, priority)
            track = self.tracks.setdefault(key, _Track())
            layer, extra = self._layer(key)
            box = self._box(ctx, draft.headline, draft.body, draft.evidence_ids, key)
            if on_screen:
                t_show = max(box_at, track.busy_until)
                track.used[m.period] = track.used.get(m.period, 0) + 1
                track.last_box_t = m.t_peak
                track.busy_until = t_show + c.box_duration_s
                show.append(key)
                cues.append(
                    base
                    | extra
                    | {
                        "_key": key,
                        "t_show": round(t_show, 1),
                        "duration": c.box_duration_s,
                        "layer": layer,
                        "template": Template.FACT_BOX,
                        "priority": priority,
                        "box": box,
                    }
                )
            else:
                cues.append(
                    base
                    | extra
                    | {
                        "_key": key,
                        "t_show": round(m.t_peak + 1.0, 1),
                        "duration": c.timeline_duration_s,
                        "layer": layer,
                        "template": Template.TIMELINE_ITEM,
                        "priority": priority,
                        "box": box,
                    }
                )
            budget_left[key] = c.boxes_per_half - track.used.get(m.period, 0)
            self.trace.add(
                m.moment_id,
                "director",
                "director",
                "schedule",
                "ok" if on_screen else "cut",
                f"{key}: {reason}",
            )
        m.director = DirectorDecision(
            show=show, camera=camera, replay_at_t=replay_at, budget_left=budget_left
        )
        m.status = MomentStatus.SCHEDULED if cues else MomentStatus.DROPPED
        if not cues:
            self.trace.add(
                m.moment_id,
                "director",
                "director",
                "schedule",
                "cut",
                "nothing to show: moment dropped",
            )
        return cues

    @staticmethod
    def _layer(key: str) -> tuple[Layer, dict[str, Any]]:
        kind, _, subject = key.partition(":")
        if kind == "player":
            return Layer.PLAYER, {"player_id": subject}
        if kind == "club":
            return Layer.CLUB, {"team_id": subject}
        return Layer.PUNDIT, {}

    def _box(
        self, ctx: MomentContext, headline: str, body: str, evidence_ids: list[str], key: str
    ) -> dict[str, Any]:
        items = [i for i in ctx.ledger.items if i.id in evidence_ids]
        notes: list[str] = []
        shares = [(c.player_id, ctx.ledger.get(f"share:{c.player_id}")) for c in ctx.contributors]
        parts = [
            f"{ctx.names.get(pid, pid)} {round(s.numbers['share'] * 100)}%"
            for pid, s in shares
            if s is not None
        ]
        if parts:
            notes.append("Contribution to the move: " + ", ".join(parts))
            items += [s for _, s in shares if s is not None and s not in items]
        analyst = AnalystDetail(event_ids=ctx.event_ids, pass_map=ctx.pass_map, notes=notes)
        return FactBox(headline=headline, body=body, evidence=items, analyst=analyst).model_dump(
            mode="json"
        )

    def _speed_badges(self, ctx: MomentContext, base: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for c in ctx.contributors:
            run = c.run
            if run is None:
                continue
            season_best = ctx.ledger.get(f"season_best:{c.player_id}") is not None
            if run.top_speed_kmh < SPEED_BADGE_KMH and not season_best:
                continue
            out.append(
                base
                | {
                    "t_show": round(run.top_speed_t, 1),
                    "duration": 3.0,
                    "layer": Layer.PLAYER,
                    "template": Template.SPEED_BADGE,
                    "player_id": c.player_id,
                    "priority": 0.0,
                    "badge": {
                        "player_id": c.player_id,
                        "speed_kmh": run.top_speed_kmh,
                        "season_best": season_best,
                    },
                }
            )
        return out
