import type { Cue, CueTrack, Frame, League, MatchEvent, MatchMeta } from "../contracts";
import type { MomentTiming } from "./clock";
import { Match } from "./match";
import { Tracks } from "./tracks";

/** The shared clock as the live server last reported it. */
export interface LiveClock {
  /** Viewer time: what every viewer is watching now. */
  v: number;
  /** How far the server has released: agents and buffers work up to here. */
  head: number;
  rate: number;
  lead: number;
  pace: "condensed" | "realtime";
  started: boolean;
  ended: boolean;
}

interface Poll {
  clock: LiveClock;
  frames: Frame[];
  events: MatchEvent[];
  moments: MomentTiming[];
  cues: Cue[];
  more: boolean;
  languages: string[];
}

const POLL_MS = 500;

/**
 * Follows a `matchlens-live` server. It polls for everything up to the server's head,
 * feeds it into the match, and keeps the server's clock so the player can sit exactly
 * at the live edge, `lead` match seconds behind what the agents have seen.
 */
export class LiveFeed {
  clock: LiveClock;
  private clockAt = performance.now();
  private timer = 0;
  private stopped = false;
  error: string | null = null;

  private constructor(
    readonly base: string,
    readonly match: Match,
    first: Poll,
  ) {
    this.clock = first.clock;
  }

  /** Connects, waits for the first frames, and returns the growing match. */
  static async connect(base: string): Promise<LiveFeed> {
    const [meta, league] = await Promise.all([get<MatchMeta>(base + "match.json"), get<League>(base + "league.json")]);
    let first = await get<Poll>(`${base}poll?frames=0&events=0&moments=0&cues=0`);
    while (first.frames.length < 2) {
      await sleep(POLL_MS);
      first = await get<Poll>(`${base}poll?frames=0&events=0&moments=0&cues=0`);
    }
    const track: CueTrack = { schema_version: meta.schema_version, match_id: meta.match_id, languages: first.languages, cues: [...first.cues] };
    const match = new Match(meta, league, [...first.events], track, new Tracks(first.frames), [...first.moments], true);
    match.ended = first.clock.ended && !first.more;
    const feed = new LiveFeed(base, match, first);
    feed.schedule(first.more ? 0 : POLL_MS);
    return feed;
  }

  /** The viewer time the server is at now, extrapolated between polls. */
  edge(now = performance.now()): number {
    const c = this.clock;
    const v = c.v + (c.rate * (now - this.clockAt)) / 1000;
    return Math.min(v, c.head, this.match.end);
  }

  stop() {
    this.stopped = true;
    window.clearTimeout(this.timer);
  }

  private schedule(ms: number) {
    if (this.stopped) return;
    this.timer = window.setTimeout(() => void this.poll(), ms);
  }

  private async poll() {
    const m = this.match;
    const url = `${this.base}poll?frames=${m.tracks.length}&events=${m.events.length}&moments=${m.moments.length}&cues=${m.cueTrack.cues.length}`;
    try {
      const p = await get<Poll>(url);
      if (p.clock.v < this.clock.v - 60) {
        // The server started the match again (`--loop`): start over with it.
        location.reload();
        return;
      }
      if (p.frames.length || p.events.length || p.cues.length || p.moments.length) {
        m.extend({ frames: p.frames, events: p.events, cues: p.cues, moments: p.moments });
      }
      this.clock = p.clock;
      this.clockAt = performance.now();
      m.ended = p.clock.ended && !p.more;
      this.error = null;
      this.schedule(p.more ? 0 : POLL_MS);
    } catch (e) {
      // The player keeps going on what it has; the feed tries again.
      this.error = String(e);
      this.schedule(POLL_MS * 4);
    }
  }
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}
