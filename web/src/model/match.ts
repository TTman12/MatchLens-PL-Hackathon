import type { Club, Cue, CueTrack, Frame, League, MatchEvent, MatchMeta, Player } from "../contracts";
import { slowSpans, type MomentTiming, type Span } from "./clock";
import { parseFrames, Tracks } from "./tracks";
import { localise } from "./cues";
import { replaySlots, type ReplaySlot } from "./replays";
import { allTrails, type SlotTrails } from "./trails";
import { attackingDirection, formatClock, toPitch, type Direction } from "./pitch";

export type MarkerKind = "goal" | "card" | "red" | "corner" | "save" | "chance";

export interface Marker {
  t: number;
  kind: MarkerKind;
  teamId: string;
  label: string;
  /** Pitch-frame point the action happened at. */
  at: [number, number];
  /** The goal being attacked, for set-piece and shot cameras. */
  attacking: Direction;
  playerId?: string;
}

export interface PlayerInfo extends Player {
  teamId: string;
  club: Club;
  slot: string;
}

/** Match time a live match is drawn against on the scrubber until it has ended. */
const NOMINAL_END_S = 96 * 60;

/** New data from a live feed, everything after what the match already holds. */
export interface MatchUpdate {
  frames?: Frame[];
  events?: MatchEvent[];
  cues?: Cue[];
  moments?: MomentTiming[];
}

/**
 * One match, loaded and indexed for playback. A file-based match is complete when it is
 * built; a live one grows through `extend` as the feed delivers frames, events and cues,
 * and `version` counts the updates so views can drop what they cached.
 */
export class Match {
  readonly clubs = new Map<string, Club>();
  readonly players = new Map<string, PlayerInfo>();
  readonly home: Club;
  readonly away: Club;
  markers: Marker[] = [];
  slots: ReplaySlot[] = [];
  readonly trails: SlotTrails = new Map();
  /** Stretches of match time the condensed clock plays at 1x. */
  spans: Span[] = [];
  version = 0;
  /** Set on a live match once the feed says it has ended. */
  ended: boolean;
  private goals: MatchEvent[] = [];
  private periodStarts: { period: number; t: number }[] = [];
  private localised = new Map<string, CueTrack["cues"]>();

  constructor(
    readonly meta: MatchMeta,
    readonly league: League,
    readonly events: MatchEvent[],
    readonly cueTrack: CueTrack,
    readonly tracks: Tracks,
    readonly moments: MomentTiming[] = [],
    readonly live = false,
  ) {
    this.ended = !live;
    for (const c of league.clubs) this.clubs.set(c.team_id, c);
    this.home = this.clubs.get(meta.home.team_id)!;
    this.away = this.clubs.get(meta.away.team_id)!;
    for (const sheet of [meta.home, meta.away]) {
      const club = this.clubs.get(sheet.team_id)!;
      for (const entry of sheet.starting) {
        const p = club.squad.find((s) => s.player_id === entry.player_id);
        if (p) this.players.set(p.player_id, { ...p, teamId: club.team_id, club, slot: entry.slot });
      }
      for (const id of sheet.bench ?? []) {
        const p = club.squad.find((s) => s.player_id === id);
        if (p) this.players.set(id, { ...p, teamId: club.team_id, club, slot: "SUB" });
      }
    }
    this.index();
  }

  /** Appends what a live feed delivered and rebuilds everything derived from it. */
  extend(u: MatchUpdate) {
    if (u.frames?.length) this.tracks.append(u.frames);
    if (u.events?.length) this.events.push(...u.events);
    if (u.cues?.length) this.cueTrack.cues.push(...u.cues);
    if (u.moments?.length) this.moments.push(...u.moments);
    this.index();
  }

  private index() {
    const events = this.events;
    this.goals = events.filter((e) => e.type === "goal");
    this.periodStarts = events
      .filter((e) => e.type === "period_start")
      .map((e) => ({ period: e.period, t: e.t }));
    if (this.periodStarts.length === 0) this.periodStarts.push({ period: 1, t: 0 });
    this.markers = buildMarkers(this, events);
    this.slots = replaySlots(this.cueTrack.cues);
    // Trails are computed once per replay window; a live match adds new windows only.
    for (const s of this.slots) if (!this.trails.has(s.id)) this.trails.set(s.id, allTrails(this.tracks, [s]).get(s.id)!);
    this.spans = slowSpans(this.moments, this.cueTrack.cues);
    this.localised.clear();
    this.version++;
  }

  get start(): number {
    return this.tracks.start;
  }

  /** The last match time there are frames for. */
  get end(): number {
    return this.tracks.end;
  }

  /** The far end of the scrubber: the match's end, or a full match's length while live. */
  get horizon(): number {
    return this.ended ? this.end : Math.max(this.end, this.start + NOMINAL_END_S);
  }

  cues(lang: string) {
    let c = this.localised.get(lang);
    if (!c) {
      c = localise(this.cueTrack.cues, lang);
      this.localised.set(lang, c);
    }
    return c;
  }

  periodAt(t: number): { period: number; t: number } {
    let cur = this.periodStarts[0]!;
    for (const p of this.periodStarts) if (p.t <= t) cur = p;
    return cur;
  }

  clock(t: number): string {
    const p = this.periodAt(t);
    return formatClock(t, p.period, p.t);
  }

  score(t: number): [number, number] {
    let home = 0;
    let away = 0;
    for (const g of this.goals) {
      if (g.t > t) break;
      home = Number(g.qualifiers?.score_home ?? home);
      away = Number(g.qualifiers?.score_away ?? away);
    }
    return [home, away];
  }

  direction(teamId: string, t: number): Direction {
    return attackingDirection(this.meta, teamId, this.periodAt(t).period);
  }

  /** Players on the pitch at kick-off, home first, in formation order. */
  lineup(teamId: string): PlayerInfo[] {
    const sheet = teamId === this.meta.home.team_id ? this.meta.home : this.meta.away;
    return sheet.starting.map((e) => this.players.get(e.player_id)).filter((p): p is PlayerInfo => !!p);
  }
}

function buildMarkers(m: Match, events: MatchEvent[]): Marker[] {
  const out: Marker[] = [];
  const name = (id?: string | null) => (id ? (m.players.get(id)?.short_name ?? id) : "");
  for (const e of events) {
    if (!e.team_id) continue;
    const dir = m.direction(e.team_id, e.t);
    const at = e.start ? toPitch(e.start, dir) : ([52.5, 34] as [number, number]);
    const base = { t: e.t, teamId: e.team_id, at, attacking: dir, playerId: e.player_id ?? undefined };
    const q = e.qualifiers ?? {};
    if (e.type === "goal") {
      out.push({ ...base, kind: "goal", label: `Goal · ${name(e.player_id)} ${q.score_home}-${q.score_away}` });
    } else if (e.type === "card") {
      const red = e.outcome !== "yellow";
      // Cards use the carded player's team; the incident is in their defensive half.
      out.push({ ...base, kind: red ? "red" : "card", label: `${red ? "Red" : "Yellow"} card · ${name(e.player_id)}` });
    } else if (e.type === "corner") {
      out.push({ ...base, kind: "corner", label: `Corner · ${m.clubs.get(e.team_id)?.short_name ?? e.team_id}` });
    } else if (e.type === "shot" && e.outcome === "saved" && (q.xg ?? 0) >= 0.15) {
      out.push({ ...base, kind: "save", label: `Big save · from ${name(e.player_id)}` });
    } else if (e.type === "shot" && e.outcome !== "goal" && (q.xg ?? 0) >= 0.3) {
      out.push({ ...base, kind: "chance", label: `Big chance · ${name(e.player_id)}` });
    }
  }
  return out;
}

export interface LoadProgress {
  loaded: number;
  total: number;
}

async function json<T>(base: string, file: string): Promise<T> {
  const r = await fetch(base + file);
  if (!r.ok) throw new Error(`${file}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

async function text(url: string, onProgress?: (p: LoadProgress) => void): Promise<string> {
  const r = await fetch(url);
  if (!r.ok || !r.body) throw new Error(`${url}: HTTP ${r.status}`);
  const total = Number(r.headers.get("content-length") ?? 0);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let s = "";
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    loaded += value.byteLength;
    s += decoder.decode(value, { stream: true });
    onProgress?.({ loaded, total });
  }
  return s + decoder.decode();
}

/**
 * Loads a match laid out like data/sample/ from `base` (a URL ending in /). The moments
 * are optional: without them the condensed clock slows for cues alone.
 */
export async function loadMatch(base: string, onProgress?: (p: LoadProgress) => void): Promise<Match> {
  const [meta, league, events, cues, moments, frames] = await Promise.all([
    json<MatchMeta>(base, "match.json"),
    json<League>(base, "league.json"),
    json<MatchEvent[]>(base, "events.json"),
    json<CueTrack>(base, "cues.json"),
    json<MomentTiming[]>(base, "moments.json").catch(() => []),
    text(base + "frames.jsonl", onProgress),
  ]);
  return new Match(meta, league, events, cues, new Tracks(parseFrames(frames)), moments);
}
