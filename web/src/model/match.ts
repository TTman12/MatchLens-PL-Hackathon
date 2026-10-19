import type { Club, CueTrack, League, MatchEvent, MatchMeta, Player } from "../contracts";
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

/** One match, loaded and indexed for playback. */
export class Match {
  readonly clubs = new Map<string, Club>();
  readonly players = new Map<string, PlayerInfo>();
  readonly home: Club;
  readonly away: Club;
  readonly markers: Marker[];
  readonly slots: ReplaySlot[];
  readonly trails: SlotTrails;
  private readonly goals: MatchEvent[];
  private readonly periodStarts: { period: number; t: number }[];
  private localised = new Map<string, CueTrack["cues"]>();

  constructor(
    readonly meta: MatchMeta,
    readonly league: League,
    readonly events: MatchEvent[],
    readonly cueTrack: CueTrack,
    readonly tracks: Tracks,
  ) {
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
    this.goals = events.filter((e) => e.type === "goal");
    this.periodStarts = events
      .filter((e) => e.type === "period_start")
      .map((e) => ({ period: e.period, t: e.t }));
    if (this.periodStarts.length === 0) this.periodStarts.push({ period: 1, t: 0 });
    this.markers = buildMarkers(this, events);
    this.slots = replaySlots(cueTrack.cues);
    this.trails = allTrails(tracks, this.slots);
  }

  get start(): number {
    return this.tracks.start;
  }

  get end(): number {
    return this.tracks.end;
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

/** Loads a match laid out like data/sample/ from `base` (a URL ending in /). */
export async function loadMatch(base: string, onProgress?: (p: LoadProgress) => void): Promise<Match> {
  const [meta, league, events, cues, frames] = await Promise.all([
    json<MatchMeta>(base, "match.json"),
    json<League>(base, "league.json"),
    json<MatchEvent[]>(base, "events.json"),
    json<CueTrack>(base, "cues.json"),
    text(base + "frames.jsonl", onProgress),
  ]);
  return new Match(meta, league, events, cues, new Tracks(parseFrames(frames)));
}
