import { useRef, useState } from "react";
import type { CameraShot } from "../contracts";
import type { Match, MarkerKind } from "../model/match";
import { SPEEDS, type Engine, type FrameView, type Speed } from "../player/engine";
import { SHOT_LABELS } from "../render/cameras";

interface Props {
  engine: Engine;
  match: Match;
  frame: FrameView;
  fullscreen: boolean;
  toggleFullscreen: () => void;
}

const MARKER_ICON: Record<MarkerKind, React.ReactNode> = {
  goal: (
    <svg viewBox="0 0 12 12">
      <circle cx="6" cy="6" r="4.2" fill="#fff" />
      <path d="M6 3.6 8.2 5.2 7.4 7.8H4.6L3.8 5.2z" fill="#0b0f14" />
    </svg>
  ),
  card: (
    <svg viewBox="0 0 12 12">
      <rect x="3.5" y="2" width="5" height="8" rx="1" fill="var(--yellow)" />
    </svg>
  ),
  red: (
    <svg viewBox="0 0 12 12">
      <rect x="3.5" y="2" width="5" height="8" rx="1" fill="var(--red)" />
    </svg>
  ),
  corner: (
    <svg viewBox="0 0 12 12">
      <path d="M3.5 10.5V1.8" stroke="#fff" strokeWidth="1.2" />
      <path d="M4 2l5 1.8L4 5.6z" fill="var(--amber)" />
    </svg>
  ),
  save: (
    <svg viewBox="0 0 12 12">
      <path d="M3 10V5.5a1 1 0 0 1 2 0V4a1 1 0 0 1 2 0v1a1 1 0 0 1 2 0v5z" fill="#fff" />
    </svg>
  ),
  chance: (
    <svg viewBox="0 0 12 12">
      <circle cx="6" cy="6" r="4" fill="none" stroke="#fff" strokeWidth="1.3" />
      <circle cx="6" cy="6" r="1.4" fill="#fff" />
    </svg>
  ),
};

export function Controls({ engine, match, frame, fullscreen, toggleFullscreen }: Props) {
  const span = match.horizon - match.start;
  const pct = (t: number) => ((t - match.start) / span) * 100;
  const [hover, setHover] = useState<number | null>(null);
  const [menu, setMenu] = useState<"speed" | "camera" | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const timeAt = (clientX: number) => {
    const r = bar.current!.getBoundingClientRect();
    return match.start + Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * span;
  };
  const speedLabel = (s: Speed) => (s === "condensed" ? "Condensed" : s === 1 ? "Normal" : `${s}×`);
  const ffLabel = () => {
    if (frame.speed !== "condensed") return `${frame.speed}×`;
    return frame.rate > 1.5 ? `${Math.round(frame.rate)}×` : "1×";
  };

  return (
    <div className="controls" onClick={(e) => e.stopPropagation()}>
      <div
        ref={bar}
        className="scrub"
        onPointerDown={(e) => {
          dragging.current = true;
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          engine.seek(timeAt(e.clientX));
        }}
        onPointerMove={(e) => {
          setHover(timeAt(e.clientX));
          if (dragging.current) engine.seek(timeAt(e.clientX));
        }}
        onPointerUp={() => (dragging.current = false)}
        onPointerLeave={() => setHover(null)}
        role="slider"
        aria-label="Seek"
        aria-valuemin={match.start}
        aria-valuemax={match.horizon}
        aria-valuenow={frame.t}
      >
        <div className="scrub-track">
          {engine.slots().map((s) => (
            <div key={s.id} className="scrub-replay" style={{ left: `${pct(s.start)}%`, width: `${pct(s.end) - pct(s.start)}%` }} />
          ))}
          {frame.live && <div className="scrub-buffer" style={{ width: `${pct(frame.t + frame.live.behind)}%` }} />}
          <div className="scrub-fill" style={{ width: `${pct(frame.t)}%` }} />
          {hover !== null && <div className="scrub-hover" style={{ width: `${pct(hover)}%` }} />}
        </div>
        <div className="scrub-head" style={{ left: `${pct(frame.t)}%` }} />
        {engine.markers().map((m) => (
          <button
            key={`${m.kind}${m.t}`}
            className={`marker marker-${m.kind}`}
            style={{ left: `${pct(m.t)}%` }}
            title={`${match.clock(m.t)} · ${m.label}`}
            onPointerDown={(e) => {
              e.stopPropagation();
              engine.seek(m.t - 4);
            }}
          >
            {MARKER_ICON[m.kind]}
          </button>
        ))}
        {hover !== null && (
          <div className="scrub-tip" style={{ left: `${pct(hover)}%` }}>
            {match.clock(hover)}
          </div>
        )}
      </div>
      <div className="ctrl-row">
        <button className="ctrl" onClick={() => engine.toggle()} aria-label={frame.playing ? "Pause" : "Play"}>
          {frame.playing ? (
            <svg viewBox="0 0 24 24">
              <path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" fill="currentColor" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z" fill="currentColor" />
            </svg>
          )}
        </button>
        <button className="ctrl" onClick={() => engine.seek(frame.t - 10)} aria-label="Back 10 seconds">
          <svg viewBox="0 0 24 24">
            <path d="M12 5V2L7 6l5 4V7a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z" fill="currentColor" />
            <text x="12" y="16" textAnchor="middle" fontSize="6.5" fontWeight="700" fill="currentColor">
              10
            </text>
          </svg>
        </button>
        <button
          className="ctrl ctrl-text"
          onClick={() => {
            const n = engine.nextMarker();
            if (n) engine.seek(n.t - 4);
          }}
          aria-label="Next moment"
          title="Next moment (N)"
        >
          Next moment
          <svg viewBox="0 0 24 24">
            <path d="M6 6l8 6-8 6zM16 6h2v12h-2z" fill="currentColor" />
          </svg>
        </button>
        <button className="ctrl" onClick={() => engine.setMuted(!frame.muted)} aria-label={frame.muted ? "Unmute" : "Mute"}>
          {frame.muted ? (
            <svg viewBox="0 0 24 24">
              <path d="M4 9v6h4l5 5V4L8 9zM16.5 9.5l5 5m0-5-5 5" stroke="currentColor" strokeWidth="1.8" fill="currentColor" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24">
              <path d="M4 9v6h4l5 5V4L8 9z" fill="currentColor" />
              <path d="M16 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12" stroke="currentColor" strokeWidth="1.8" fill="none" />
            </svg>
          )}
        </button>
        <div className="ctrl-time">
          <b>{frame.clock}</b>
          {!frame.live && <span> / {match.clock(match.end)}</span>}
        </div>
        {frame.live && (
          <button
            className={`ctrl ctrl-text go-live${frame.live.atEdge ? " is-live" : ""}`}
            onClick={() => engine.goLive()}
            title={`Viewers watch ${Math.round(frame.live.delay / 60)} match minutes behind the agents`}
          >
            <span className="live-dot" />
            {frame.live.atEdge ? "Live" : `Go live (−${match.clock(match.start + frame.live.behind).replace(/^0/, "")})`}
          </button>
        )}
        <div className="ctrl-spacer" />
        <div className="ctrl-menu-wrap">
          <button className="ctrl ctrl-text" onClick={() => setMenu(menu === "camera" ? null : "camera")} aria-haspopup="menu">
            <svg viewBox="0 0 24 24">
              <path d="M4 7h11v10H4zM15 10l5-3v10l-5-3z" fill="currentColor" />
            </svg>
            {frame.forcedShot ? SHOT_LABELS[frame.forcedShot] : "Auto"}
          </button>
          {menu === "camera" && (
            <div className="ctrl-menu" role="menu">
              <div className="ctrl-menu-title">Camera</div>
              {[null, ...(Object.keys(SHOT_LABELS) as CameraShot[])].map((s) => (
                <button
                  key={s ?? "auto"}
                  role="menuitemradio"
                  aria-checked={frame.forcedShot === s}
                  className={frame.forcedShot === s ? "is-on" : ""}
                  onClick={() => {
                    engine.forceShot(s);
                    setMenu(null);
                  }}
                >
                  {s ? SHOT_LABELS[s] : "Auto (director)"}
                </button>
              ))}
            </div>
          )}
        </div>
        {frame.live ? (
          <span className="ctrl ctrl-text ctrl-static" title="The live server sets the pace for every viewer">
            {frame.live.atEdge && frame.rate > 1.5 ? `${Math.round(frame.rate)}×` : "1×"}
          </span>
        ) : (
          <div className="ctrl-menu-wrap">
            <button className="ctrl ctrl-text" onClick={() => setMenu(menu === "speed" ? null : "speed")} aria-haspopup="menu">
              {ffLabel()}
            </button>
            {menu === "speed" && (
              <div className="ctrl-menu" role="menu">
                <div className="ctrl-menu-title">Speed</div>
                {(["condensed", ...SPEEDS] as Speed[]).map((s) => (
                  <button
                    key={s}
                    role="menuitemradio"
                    aria-checked={frame.speed === s}
                    className={frame.speed === s ? "is-on" : ""}
                    onClick={() => {
                      engine.setSpeed(s);
                      setMenu(null);
                    }}
                  >
                    {speedLabel(s)}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <button className="ctrl" onClick={toggleFullscreen} aria-label={fullscreen ? "Exit full screen" : "Full screen"}>
          {fullscreen ? (
            <svg viewBox="0 0 24 24">
              <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" stroke="currentColor" strokeWidth="2" fill="none" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24">
              <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" stroke="currentColor" strokeWidth="2" fill="none" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
