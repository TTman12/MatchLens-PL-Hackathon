import { useEffect, useRef, useState } from "react";
import type { Match } from "../model/match";
import type { LiveFeed } from "../model/live";
import type { Viewer } from "../model/viewer";
import type { Engine } from "../player/engine";
import { Logo } from "./App";
import { LensPanel } from "./LensPanel";
import { MatchPanel } from "./MatchPanel";
import { PlayerView } from "./PlayerView";

interface Props {
  match: Match;
  feed: LiveFeed | null;
  viewer: Viewer;
  setViewer: (v: Viewer) => void;
}

export function Shell({ match, feed, viewer, setViewer }: Props) {
  const [engine, setEngine] = useState<Engine | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const playerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const on = () => setFullscreen(document.fullscreenElement === playerRef.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);

  useEffect(() => {
    engine?.setViewer(viewer);
  }, [engine, viewer]);

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void playerRef.current?.requestFullscreen?.();
  };

  const { home, away } = match;
  return (
    <div className="app">
      <header className="topbar">
        <Logo />
        <div className="topbar-match">
          <span className="crest" style={{ background: home.colours.primary }} />
          {home.name} <span className="vs">v</span> {away.name}
          <span className="crest" style={{ background: away.colours.primary }} />
        </div>
        <div className="topbar-meta">
          {feed && <span className="topbar-live">Live · {Math.round(feed.clock.lead / 60)} min delay</span>}
          {match.league.name} · Matchday {match.meta.matchday}
        </div>
      </header>
      <aside className="side side-left">
        <LensPanel match={match} viewer={viewer} setViewer={setViewer} />
      </aside>
      <main className="stage-col">
        <div ref={playerRef} className={`player-frame${fullscreen ? " is-fullscreen" : ""}`}>
          <PlayerView
            match={match}
            feed={feed}
            viewer={viewer}
            setViewer={setViewer}
            onEngine={setEngine}
            fullscreen={fullscreen}
            toggleFullscreen={toggleFullscreen}
          />
        </div>
      </main>
      <aside className="side side-right">{engine && <MatchPanel match={match} engine={engine} viewer={viewer} />}</aside>
    </div>
  );
}
