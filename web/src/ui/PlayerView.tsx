import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { Match } from "../model/match";
import type { LiveFeed } from "../model/live";
import { LENSES, type Viewer } from "../model/viewer";
import { Engine } from "../player/engine";
import { Stage } from "../render/stage";
import { Controls } from "./Controls";
import { LensOverlay, ReplayBug, ScoreBug, Stinger, SweepBar } from "./Overlays";

interface Props {
  match: Match;
  feed: LiveFeed | null;
  viewer: Viewer;
  setViewer: (v: Viewer) => void;
  onEngine: (e: Engine | null) => void;
  fullscreen: boolean;
  toggleFullscreen: () => void;
}

export function PlayerView({ match, feed, viewer, setViewer, onEngine, fullscreen, toggleFullscreen }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [engine, setEngine] = useState<Engine | null>(null);
  const viewerRef = useRef(viewer);
  viewerRef.current = viewer;

  useEffect(() => {
    const canvas = canvasRef.current!;
    const box = boxRef.current!;
    let stage: Stage;
    try {
      stage = new Stage(canvas, match);
    } catch (e) {
      console.error(e);
      return;
    }
    const resize = () => stage.resize(box.clientWidth, box.clientHeight);
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(box);
    const eng = new Engine(match, stage, viewerRef.current, feed);
    // `?t=<seconds>` opens the match at a moment, for sharing a link or recording a demo.
    const startAt = Number(new URLSearchParams(location.search).get("t"));
    if (startAt > 0) eng.seek(startAt);
    eng.start();
    setEngine(eng);
    // Handy for scripted demo recordings and debugging from the console.
    (window as unknown as { matchlens?: Engine }).matchlens = eng;
    onEngine(eng);
    return () => {
      ro.disconnect();
      eng.stop();
      eng.pause();
      stage.dispose();
      onEngine(null);
    };
  }, [match, feed, onEngine]);

  // Keyboard: space play/pause, arrows seek, f full screen, m mute, n next moment, 1-3 lens.
  useEffect(() => {
    if (!engine) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
      const s = engine.getSnapshot();
      if (e.key === " " || e.key === "k") engine.toggle();
      else if (e.key === "ArrowRight") engine.seek(s.t + 5);
      else if (e.key === "ArrowLeft") engine.seek(s.t - 5);
      else if (e.key === "f") toggleFullscreen();
      else if (e.key === "m") engine.setMuted(!s.muted);
      else if (e.key === "n") {
        const next = engine.nextMarker();
        if (next) engine.seek(next.t - 4);
      } else if (["1", "2", "3"].includes(e.key)) {
        setViewer({ ...viewerRef.current, lens: LENSES[Number(e.key) - 1]!.id });
      } else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [engine, setViewer, toggleFullscreen]);

  return (
    <div ref={boxRef} className="player">
      <canvas ref={canvasRef} className="player-canvas" />
      <div className="vignette" />
      {engine ? (
        <Hud engine={engine} match={match} fullscreen={fullscreen} toggleFullscreen={toggleFullscreen} />
      ) : (
        <div className="player-fallback">This player needs WebGL. Try a recent Chrome, Edge, Safari or Firefox.</div>
      )}
    </div>
  );
}

function Hud({
  engine,
  match,
  fullscreen,
  toggleFullscreen,
}: {
  engine: Engine;
  match: Match;
  fullscreen: boolean;
  toggleFullscreen: () => void;
}) {
  const f = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  const [idle, setIdle] = useState(false);
  const timer = useRef(0);

  // Controls hide after a moment of no mouse movement while playing.
  const wake = () => {
    setIdle(false);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setIdle(true), 2800);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const hideChrome = idle && f.playing;

  return (
    <div className={`hud${hideChrome ? " is-idle" : ""}`} onMouseMove={wake} onClick={wake}>
      <div className="hud-click" onClick={() => engine.toggle()} onDoubleClick={toggleFullscreen} />
      <ScoreBug match={match} frame={f} />
      <ReplayBug frame={f} />
      {f.sweep && (
        <div className="lens-layer" style={{ clipPath: `inset(0 0 0 ${f.sweep.at * 100}%)` }}>
          <LensOverlay view={f.sweep.previous} match={match} engine={engine} />
        </div>
      )}
      <div className="lens-layer" style={f.sweep ? { clipPath: `inset(0 ${(1 - f.sweep.at) * 100}% 0 0)` } : undefined}>
        <LensOverlay view={f.lens} match={match} engine={engine} />
      </div>
      {f.sweep && <SweepBar at={f.sweep.at} from={f.sweep.previous} to={f.lens} />}
      <Stinger slotId={f.slot?.id ?? null} />
      {!f.playing && (f.live ? !engine.hasPlayed : f.t <= match.start + 0.01) && (
        <button className="big-play" onClick={() => (f.live ? engine.goLive() : engine.play())} aria-label="Play">
          <svg viewBox="0 0 24 24">
            <path d="M8 5v14l11-7z" fill="currentColor" />
          </svg>
          <span>{f.live ? "Join live" : "Watch the match"}</span>
        </button>
      )}
      <Controls engine={engine} match={match} frame={f} fullscreen={fullscreen} toggleFullscreen={toggleFullscreen} />
    </div>
  );
}
