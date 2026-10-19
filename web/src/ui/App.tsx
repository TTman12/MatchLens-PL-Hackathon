import { useEffect, useState } from "react";
import { loadMatch, type LoadProgress, type Match } from "../model/match";
import { LiveFeed } from "../model/live";
import type { Viewer } from "../model/viewer";
import { Shell } from "./Shell";

const slash = (base: string) => (base.endsWith("/") ? base : base + "/");

/**
 * Where the match comes from. `?live` follows a `matchlens-live` server on this origin
 * (`?live=<url>/` elsewhere). Otherwise files: `?data=<url>/`, then VITE_DATA_URL, then
 * the demo match if it has been built (`matchlens-demo`), then the bundled sample.
 */
function source(): { live: string } | { files: string[] } {
  const q = new URLSearchParams(location.search);
  if (q.has("live")) return { live: slash(q.get("live") || "/live/") };
  const base = q.get("data") ?? import.meta.env.VITE_DATA_URL;
  return { files: base ? [slash(base)] : ["/data/demo/", "/data/sample/"] };
}

async function load(onProgress: (p: LoadProgress) => void): Promise<{ match: Match; feed: LiveFeed | null }> {
  const src = source();
  if ("live" in src) {
    const feed = await LiveFeed.connect(src.live);
    return { match: feed.match, feed };
  }
  let error: unknown = null;
  for (const base of src.files) {
    try {
      return { match: await loadMatch(base, onProgress), feed: null };
    } catch (e) {
      error = e;
    }
  }
  throw error;
}

const STORE_KEY = "matchlens.viewer";

function initialViewer(m: Match): Viewer {
  const fallback: Viewer = {
    lens: "player",
    // Default to the player with the most moments to show, so the first goal lands.
    playerId: busiestPlayer(m),
    teamId: m.home.team_id,
    lang: "en",
  };
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) ?? "null") as Partial<Viewer> | null;
    if (!saved) return fallback;
    return {
      lens: saved.lens ?? fallback.lens,
      playerId: saved.playerId && m.players.has(saved.playerId) ? saved.playerId : fallback.playerId,
      teamId: saved.teamId && m.clubs.has(saved.teamId) ? saved.teamId : fallback.teamId,
      lang: saved.lang && m.cueTrack.languages.includes(saved.lang) ? saved.lang : fallback.lang,
    };
  } catch {
    return fallback;
  }
}

function busiestPlayer(m: Match): string {
  const count = new Map<string, number>();
  for (const c of m.cueTrack.cues) if (c.player_id) count.set(c.player_id, (count.get(c.player_id) ?? 0) + (c.priority ?? 0));
  let best = m.lineup(m.home.team_id).at(-2)?.player_id ?? [...m.players.keys()][0]!;
  let n = -1;
  for (const [id, k] of count) if (k > n) [best, n] = [id, k];
  return best;
}

export function App() {
  const [match, setMatch] = useState<Match | null>(null);
  const [feed, setFeed] = useState<LiveFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<LoadProgress>({ loaded: 0, total: 0 });
  const [viewer, setViewer] = useState<Viewer | null>(null);

  useEffect(() => {
    let live = true;
    let opened: LiveFeed | null = null;
    load((p) => live && setProgress(p))
      .then(({ match: m, feed: f }) => {
        opened = f;
        if (!live) return f?.stop();
        setMatch(m);
        setFeed(f);
        setViewer(initialViewer(m));
      })
      .catch((e: unknown) => live && setError(String(e)));
    return () => {
      live = false;
      opened?.stop();
    };
  }, []);

  useEffect(() => {
    if (!viewer) return;
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(viewer));
    } catch {
      // Private mode or blocked storage: preferences just aren't remembered.
    }
  }, [viewer]);

  if (error) {
    return (
      <div className="splash">
        <Logo />
        <p className="splash-error">Couldn't load the match. {error}</p>
      </div>
    );
  }
  if (!match || !viewer) {
    const pct = progress.total ? Math.round((progress.loaded / progress.total) * 100) : null;
    return (
      <div className="splash">
        <Logo />
        <div className="splash-bar">
          <div style={{ width: `${pct ?? 30}%` }} className={pct === null ? "indeterminate" : ""} />
        </div>
        <p className="splash-note">
          {"live" in source() ? "Joining the live match" : "Loading tracking data"}
          {pct !== null ? ` · ${pct}%` : ""}
        </p>
      </div>
    );
  }
  return <Shell match={match} feed={feed} viewer={viewer} setViewer={setViewer} />;
}

export function Logo() {
  return (
    <div className="logo">
      <svg viewBox="0 0 32 32" aria-hidden>
        <circle cx="16" cy="16" r="12" fill="none" stroke="currentColor" strokeWidth="3.5" />
        <circle cx="16" cy="16" r="4" fill="currentColor" />
        <path d="M25 25 L30 30" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" />
      </svg>
      <span>
        Match<b>Lens</b>
      </span>
    </div>
  );
}
