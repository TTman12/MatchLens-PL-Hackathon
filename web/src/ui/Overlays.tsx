import { useEffect, useRef, useState } from "react";
import type { FactBox as Box, Cue } from "../contracts";
import type { Match } from "../model/match";
import type { ScheduledBox } from "../model/cues";
import { LENSES } from "../model/viewer";
import type { Engine, FrameView, LensView, Tag } from "../player/engine";
import { SHOT_LABELS } from "../render/cameras";
import { t as tr } from "./i18n";

export function ScoreBug({ match, frame }: { match: Match; frame: FrameView }) {
  const [h, a] = frame.score;
  const team = (c: typeof match.home) => (
    <div className="sb-team" style={{ ["--club" as string]: c.colours.primary, ["--club-2" as string]: c.colours.secondary }}>
      <span className="sb-stripe" />
      {c.team_id.toUpperCase()}
    </div>
  );
  return (
    <div className="scorebug">
      <div className="sb-mark" aria-hidden>
        ML
      </div>
      {team(match.home)}
      <div className="sb-score">
        <span key={`h${h}`} className="sb-n">
          {h}
        </span>
        <span className="sb-dash">–</span>
        <span key={`a${a}`} className="sb-n">
          {a}
        </span>
      </div>
      {team(match.away)}
      <div className="sb-clock">{frame.clock}</div>
    </div>
  );
}

export function ReplayBug({ frame }: { frame: FrameView }) {
  if (!frame.slot) {
    return (
      <div className="livebug">
        <span className="live-dot" /> LIVE
        {frame.shot !== "tv_main" && <span className="cam-label">{SHOT_LABELS[frame.shot]}</span>}
        {frame.rate > 1.5 && (
          <span className="ff-badge" title="Condensed clock: fast between moments, real time for every moment that matters">
            <svg viewBox="0 0 24 24" aria-hidden>
              <path d="M3 6l9 6-9 6zM12 6l9 6-9 6z" fill="currentColor" />
            </svg>
            {Math.round(frame.rate)}×
          </span>
        )}
      </div>
    );
  }
  return (
    <div className="replaybug">
      <span className="rb-word">REPLAY</span>
      <span className="rb-shot">{SHOT_LABELS[frame.shot]}</span>
      {frame.replaySpeed > 0 && frame.replaySpeed < 1 && <span className="rb-speed">{frame.replaySpeed}×</span>}
    </div>
  );
}

export function LensOverlay({ view, match, engine }: { view: LensView; match: Match; engine: Engine }) {
  const lens = LENSES.find((l) => l.id === view.viewer.lens)!;
  const lang = view.viewer.lang;
  const subject =
    view.viewer.lens === "player"
      ? match.players.get(view.viewer.playerId)?.short_name
      : view.viewer.lens === "club"
        ? match.clubs.get(view.viewer.teamId)?.short_name
        : null;
  return (
    <div className="lens-overlay" style={{ ["--accent" as string]: view.accent }}>
      <div className="lens-chip">
        <span className="lens-chip-dot" />
        {tr(lang, lens.id)}
        {subject && <b>{subject}</b>}
      </div>
      {view.tags.map((t) => (
        <PlayerTag key={t.playerId} tag={t} />
      ))}
      {view.notInvolved && (
        <div className="not-involved-chip">
          {match.players.get(view.viewer.playerId)?.short_name} · {tr(lang, "not_involved")}
        </div>
      )}
      {view.box && <BoxCard key={view.box.key} box={view.box} view={view} match={match} engine={engine} />}
    </div>
  );
}

function PlayerTag({ tag }: { tag: Tag }) {
  return (
    <div
      className={`ptag ${tag.major ? "ptag-major" : "ptag-minor"}`}
      style={{ transform: `translate(${tag.x}px, ${tag.y}px)`, ["--club" as string]: tag.color }}
    >
      <div className="ptag-inner">
        {tag.badgeKmh !== undefined && <div className="speed-pop">
            <span>TOP SPEED</span> {tag.badgeKmh.toFixed(1)} km/h
          </div>}
        {tag.speedKmh !== undefined && tag.peakKmh !== undefined && (
          <Speedometer speed={tag.speedKmh} peak={tag.peakKmh} />
        )}
        <div className="ptag-label">
          <span className="ptag-num">{tag.shirt}</span>
          <span className="ptag-name">{tag.name}</span>
        </div>
        <div className="ptag-stem" />
      </div>
    </div>
  );
}

const GAUGE_MAX = 40;

/** Small arc gauge: needle at the current speed, a tick and label at the window's peak. */
export function Speedometer({ speed, peak }: { speed: number; peak: number }) {
  const r = 22;
  const toAng = (v: number) => Math.PI * (1 - Math.min(v, GAUGE_MAX) / GAUGE_MAX);
  const pt = (v: number, rr: number) => [28 + Math.cos(toAng(v)) * rr, 28 - Math.sin(toAng(v)) * rr] as const;
  const arc = (v: number) => {
    const [x, y] = pt(v, r);
    return `M ${28 - r} 28 A ${r} ${r} 0 0 1 ${x.toFixed(2)} ${y.toFixed(2)}`;
  };
  const [nx, ny] = pt(speed, r - 5);
  const [px1, py1] = pt(peak, r - 4);
  const [px2, py2] = pt(peak, r + 4);
  return (
    <div className="speedo">
      <svg viewBox="0 0 56 32" aria-hidden>
        <path d={arc(GAUGE_MAX)} className="speedo-track" />
        <path d={arc(speed)} className="speedo-fill" />
        <line x1={px1} y1={py1} x2={px2} y2={py2} className="speedo-peak" />
        <line x1={28} y1={28} x2={nx} y2={ny} className="speedo-needle" />
        <circle cx={28} cy={28} r={2.4} className="speedo-hub" />
      </svg>
      <div className="speedo-read">
        <b>{speed.toFixed(1)}</b>
        <span>km/h</span>
      </div>
      <div className="speedo-peak-label">PEAK {peak.toFixed(1)}</div>
    </div>
  );
}

function BoxCard({ box, view, match, engine }: { box: ScheduledBox; view: LensView; match: Match; engine: Engine }) {
  const [open, setOpen] = useState(false);
  const lang = view.viewer.lang;
  if (!box.cue || !box.cue.box) {
    const name = match.players.get(box.notInvolved?.playerId ?? "")?.short_name ?? "";
    return (
      <div className="factbox factbox-quiet">
        <div className="fb-kicker">{tr(lang, "player")}</div>
        <div className="fb-quiet">
          <b>{name}</b> · {tr(lang, "not_involved")}
        </div>
      </div>
    );
  }
  const cue = box.cue;
  const fb = cue.box!;
  return (
    <div className={`factbox${open ? " is-open" : ""}`} onClick={(e) => e.stopPropagation()}>
      <div className="fb-progress" style={{ transform: `scaleX(${1 - (engine.getSnapshot().t - box.start) / (box.end - box.start)})` }} />
      <div className="fb-kicker">
        <span className="fb-kicker-dot" />
        {kicker(cue, match, lang)}
      </div>
      <div className="fb-headline">{fb.headline}</div>
      {fb.body && <div className="fb-body">{fb.body}</div>}
      {(fb.evidence?.length || fb.analyst) && (
        <button className="fb-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
          {tr(lang, open ? "hide_evidence" : "show_evidence")}
          <svg viewBox="0 0 12 12" aria-hidden>
            <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </button>
      )}
      {open && <Evidence box={fb} match={match} />}
    </div>
  );
}

function kicker(cue: Cue, match: Match, lang: string): string {
  if (cue.layer === "player") return `${tr(lang, "player")} · ${match.players.get(cue.player_id ?? "")?.name ?? ""}`;
  if (cue.layer === "club") return `${tr(lang, "club")} · ${match.clubs.get(cue.team_id ?? "")?.name ?? ""}`;
  if (cue.layer === "pundit") return tr(lang, "pundit");
  return "MatchLens";
}

function Evidence({ box, match }: { box: Box; match: Match }) {
  const a = box.analyst;
  return (
    <div className="fb-evidence">
      {box.evidence?.map((e) => (
        <div key={e.id} className="ev">
          <span className={`ev-type ev-${e.claim_type}`}>{e.claim_type.replace("_", " ")}</span>
          <span className="ev-value">{e.value}</span>
          <code className="ev-src">
            {e.id} · {e.source}
          </code>
        </div>
      ))}
      {a?.notes?.map((n) => (
        <div key={n} className="ev ev-note">
          {n}
        </div>
      ))}
      {a?.pass_map && a.pass_map.length > 0 && <PassMap segments={a.pass_map as number[][]} match={match} />}
      {a?.event_ids && a.event_ids.length > 0 && (
        <div className="ev-ids">
          {a.event_ids.map((id) => (
            <code key={id}>{id}</code>
          ))}
        </div>
      )}
    </div>
  );
}

function PassMap({ segments }: { segments: number[][]; match: Match }) {
  // Pitch frame, y up from the near touchline: flip for SVG.
  return (
    <svg className="passmap" viewBox="-2 -2 109 72" aria-label="Pass map">
      <rect x="0" y="0" width="105" height="68" className="pm-pitch" />
      <line x1="52.5" y1="0" x2="52.5" y2="68" className="pm-line" />
      <circle cx="52.5" cy="34" r="9.15" className="pm-line" />
      <rect x="0" y="13.84" width="16.5" height="40.32" className="pm-line" />
      <rect x="88.5" y="13.84" width="16.5" height="40.32" className="pm-line" />
      <defs>
        <marker id="pm-head" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" markerHeight="5" orient="auto">
          <path d="M0 0 6 3 0 6z" className="pm-head" />
        </marker>
      </defs>
      {segments.map(([x1, y1, x2, y2], i) => (
        <line key={i} x1={x1} y1={68 - y1!} x2={x2} y2={68 - y2!} className="pm-pass" markerEnd="url(#pm-head)" />
      ))}
    </svg>
  );
}

export function SweepBar({ at, from, to }: { at: number; from: LensView; to: LensView }) {
  const label = LENSES.find((l) => l.id === to.viewer.lens)!;
  return (
    <div
      className="sweep-bar"
      style={{ left: `${at * 100}%`, ["--accent" as string]: to.accent, ["--accent-old" as string]: from.accent }}
    >
      <div className="sweep-label">{tr(to.viewer.lang, label.id)}</div>
    </div>
  );
}

/** A quick branded wipe when cutting into or out of a replay. */
export function Stinger({ slotId }: { slotId: string | null }) {
  const prev = useRef(slotId);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (prev.current !== slotId) {
      prev.current = slotId;
      setN((k) => k + 1);
    }
  }, [slotId]);
  if (n === 0) return null;
  return (
    <div key={n} className="stinger" aria-hidden>
      <div className="stinger-band" />
      <div className="stinger-mark">ML</div>
    </div>
  );
}
