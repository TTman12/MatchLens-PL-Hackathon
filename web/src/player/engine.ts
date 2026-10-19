import type { Camera, CameraShot, Cue } from "../contracts";
import type { Marker, Match } from "../model/match";
import { rateAt } from "../model/clock";
import type { LiveFeed } from "../model/live";
import { badgesAt, boxAt, scheduleBoxes, type ScheduledBox } from "../model/cues";
import { replayCameraFor, replayTime, slotAt, type ReplaySlot } from "../model/replays";
import type { Viewer } from "../model/viewer";
import { poseFor, type ShotContext } from "../render/cameras";
import { NO_GRAPHICS, type LensGraphics, type Stage } from "../render/stage";
import { Crowd } from "../audio/crowd";

export const SPEEDS = [0.5, 1, 2, 4] as const;
/** The playback speed setting: the condensed clock, or a fixed multiple of real time. */
export type Speed = "condensed" | (typeof SPEEDS)[number];
export const SWEEP_MS = 650;
const LENS_ACCENT = { player: "#33e1a1", pundit: "#ffb547" } as const;

export interface Tag {
  playerId: string;
  name: string;
  shirt: number;
  color: string;
  x: number;
  y: number;
  major: boolean;
  speedKmh?: number;
  peakKmh?: number;
  badgeKmh?: number;
}

/** What one viewer's lens puts on screen this frame. */
export interface LensView {
  viewer: Viewer;
  accent: string;
  graphics: LensGraphics;
  box: ScheduledBox | null;
  tags: Tag[];
  /** Set during a replay the selected player had no part in. */
  notInvolved: boolean;
}

export interface FrameView {
  t: number;
  viewT: number;
  clock: string;
  score: [number, number];
  playing: boolean;
  /** Match seconds per wall second right now. */
  rate: number;
  speed: Speed;
  muted: boolean;
  slot: ReplaySlot | null;
  replaySpeed: number;
  shot: CameraShot;
  forcedShot: CameraShot | null;
  lens: LensView;
  /** The lens being swept away, and how far the bar has travelled (0 to 1). */
  sweep: { at: number; previous: LensView } | null;
  ended: boolean;
  /** Set when following a live server: whether we sit at the live edge or behind it. */
  live: { atEdge: boolean; behind: number; delay: number } | null;
}

type Listener = () => void;

/**
 * The client-side director: owns the playback clock, decides what is on screen for
 * the viewer at each frame, and drives the three.js stage. Everything here is a pure
 * function of (match, viewer, t) apart from camera smoothing, so scrubbing is exact.
 */
export class Engine {
  private listeners = new Set<Listener>();
  private snapshot: FrameView;
  private viewer: Viewer;
  private previous: { viewer: Viewer; since: number } | null = null;
  private schedules = new Map<string, ScheduledBox[]>();
  private t: number;
  private playing = false;
  private speed: Speed = "condensed";
  private rate = 1;
  /** Live only: stay pinned to the server's clock until the viewer pauses or rewinds. */
  private following = true;
  private seenVersion = -1;
  private muted = false;
  private lastWall = 0;
  /** Seconds of wall time the engine has run, for animations that ignore the match clock. */
  private wall = 0;
  private raf = 0;
  private follow: [number, number] = [52.5, 34];
  private lastShotKey = "";
  private shotStartedAt = 0;
  private snapNext = true;
  private forcedShot: CameraShot | null = null;
  private tmpBall: [number, number, number] = [0, 0, 0];
  private tmpPos: [number, number] = [0, 0];
  readonly crowd = new Crowd();

  constructor(
    readonly match: Match,
    private stage: Stage,
    viewer: Viewer,
    readonly feed: LiveFeed | null = null,
  ) {
    this.viewer = viewer;
    this.t = feed ? feed.edge() : match.start;
    this.seenVersion = match.version;
    this.snapshot = this.compute(0);
  }

  // ---- React store ------------------------------------------------------------

  subscribe = (fn: Listener) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  getSnapshot = () => this.snapshot;

  // ---- controls ---------------------------------------------------------------

  start() {
    const loop = (now: number) => {
      const dt = this.lastWall ? Math.min(0.1, (now - this.lastWall) / 1000) : 0;
      this.lastWall = now;
      this.tick(dt);
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop() {
    cancelAnimationFrame(this.raf);
    this.lastWall = 0;
  }

  /** Whether playback has ever started (live shows "Join live" until then). */
  hasPlayed = false;

  play() {
    this.hasPlayed = true;
    if (!this.feed && this.t >= this.match.end - 0.05) this.seek(this.match.start);
    this.playing = true;
    this.crowd.start();
    this.crowd.setActive(true);
  }

  pause() {
    this.playing = false;
    this.following = false;
    this.crowd.setActive(false);
  }

  toggle() {
    if (this.playing) this.pause();
    else this.play();
  }

  seek(t: number) {
    const last = this.feed ? this.feed.edge() : this.match.end;
    this.t = Math.min(last, Math.max(this.match.start, t));
    if (this.feed) this.following = this.t >= last - 0.5;
    this.snapNext = true;
  }

  /** Live only: jump back to the live edge and stay there. */
  goLive() {
    if (!this.feed) return;
    this.seek(this.feed.edge());
    this.following = true;
    this.play();
  }

  setSpeed(s: Speed) {
    this.speed = s;
  }

  setMuted(m: boolean) {
    this.muted = m;
    this.crowd.setMuted(m);
  }

  forceShot(s: CameraShot | null) {
    this.forcedShot = s;
    this.snapNext = true;
  }

  /** Lens changes sweep; everything else (favourite player, club, language) is instant. */
  setViewer(v: Viewer) {
    if (v.lens !== this.viewer.lens) this.previous = { viewer: this.viewer, since: this.wall };
    this.viewer = v;
  }

  /** The next moment marker after the current time, to jump a few seconds before it. */
  nextMarker(): Marker | null {
    return this.markers().find((m) => m.t > this.t + 4.5) ?? null;
  }

  /**
   * Moment markers the viewer may see. Live, the feed runs minutes ahead of the viewer,
   * so markers past the live edge stay hidden: no spoilers from the broadcast delay.
   */
  markers(): Marker[] {
    if (!this.feed) return this.match.markers;
    const edge = this.feed.edge();
    return this.match.markers.filter((m) => m.t <= edge);
  }

  /** Replay slots the viewer may see on the scrubber, by the same rule. */
  slots(): ReplaySlot[] {
    if (!this.feed) return this.match.slots;
    const edge = this.feed.edge();
    return this.match.slots.filter((s) => s.start <= edge);
  }

  // ---- per frame --------------------------------------------------------------

  private schedule(v: Viewer): ScheduledBox[] {
    const key = `${v.lens}|${v.playerId}|${v.teamId}|${v.lang}`;
    let s = this.schedules.get(key);
    if (!s) {
      s = scheduleBoxes(this.match.cues(v.lang), v);
      this.schedules.set(key, s);
    }
    return s;
  }

  /**
   * Advances by `dt` seconds of wall time and draws a frame. The animation loop calls
   * this; so can a scripted recording after `stop()`, for frame-exact demo captures.
   */
  tick(dt: number) {
    this.wall += dt;
    if (this.match.version !== this.seenVersion) {
      // A live feed added frames, events or cues: drop cached schedules, add new trails.
      this.seenVersion = this.match.version;
      this.schedules.clear();
      this.stage.syncTrails();
    }
    this.rate = this.speed === "condensed" ? rateAt(this.t, this.match.spans) : this.speed;
    if (this.playing) {
      const before = this.t;
      if (this.feed && this.following) {
        this.t = Math.max(this.t, this.feed.edge());
      } else {
        const last = this.feed ? this.feed.edge() : this.match.end;
        this.t = Math.min(last, this.t + dt * this.rate);
        if (this.feed && this.t >= last - 0.05) this.following = true;
      }
      if (this.feed) this.rate = this.feed.clock.rate;
      for (const m of this.match.markers) if (m.kind === "goal" && before < m.t && this.t >= m.t) this.crowd.roar();
      if (this.match.ended && this.t >= this.match.end) this.pause();
    }
    this.snapshot = this.compute(dt);
    for (const fn of this.listeners) fn();
  }

  private compute(dt: number): FrameView {
    const now = this.wall;
    const m = this.match;
    const t = this.t;
    const v = this.viewer;

    // Replay or live? The replay shown is the viewer's own variant of it.
    const slot = slotAt(m.slots, t, v);
    let viewT = t;
    let replaySpeed = 1;
    let camera: Camera | null = null;
    if (slot) {
      const rt = replayTime(slot, t);
      viewT = rt.t;
      replaySpeed = rt.speed;
      camera = replayCameraFor(slot, v);
    }

    // Camera shot and the context it frames.
    const ball = m.tracks.ballAt(viewT, this.tmpBall);
    let shot: CameraShot = camera?.shot ?? "tv_main";
    let marker: Marker | null = slot ? markerFor(m, slot) : null;
    if (!slot) {
      const corner = m.markers.find((k) => k.kind === "corner" && t >= k.t - 9 && t < k.t + 2.5);
      if (corner) {
        shot = "corner_low";
        marker = corner;
      }
    }
    if (this.forcedShot) shot = this.forcedShot;
    const shotKey = `${shot}|${slot?.id ?? "live"}`;
    const cut = shotKey !== this.lastShotKey || this.snapNext;
    if (cut) {
      this.lastShotKey = shotKey;
      this.shotStartedAt = now;
      this.follow = [ball[0], ball[1]];
    } else {
      // Follow the ball with a slight lead, smoothed so the camera glides.
      const ahead = m.tracks.ballAt(viewT + 0.6, [0, 0, 0]);
      const k = 1 - Math.exp(-dt * (shot === "tv_main" ? 2.2 : 3));
      this.follow[0] += (ahead[0] - this.follow[0]) * k;
      this.follow[1] += (ahead[1] - this.follow[1]) * k;
    }
    let focus: [number, number] = marker?.at ?? [ball[0], ball[1]];
    const focusId = camera?.highlight ?? (slot ? marker?.playerId : undefined);
    if (focusId && m.tracks.playerAt(focusId, viewT, this.tmpPos)) focus = [this.tmpPos[0], this.tmpPos[1]];
    if (camera?.focus) focus = camera.focus as [number, number];
    const attacking = marker?.attacking ?? (m.direction(m.home.team_id, t) === "+x" ? "+x" : "-x");
    const ctx: ShotContext = {
      ball: [ball[0], ball[1], ball[2]],
      follow: this.follow,
      attacking: shot === "corner_low" && marker ? marker.attacking : attacking,
      focus,
      u: now - this.shotStartedAt,
    };
    // In the Player lens, a replay the favourite took part in keeps them in shot.
    if (slot && v.lens === "player" && slot.cues.some((c) => c.player_id === v.playerId)) {
      if (m.tracks.playerAt(v.playerId, viewT, this.tmpPos)) ctx.keep = [this.tmpPos[0], this.tmpPos[1]];
    }
    this.stage.setFrame(viewT, now);
    this.stage.setPose(poseFor(shot, ctx), dt, cut);
    this.snapNext = false;

    const lens = this.lensView(v, t, viewT, slot);
    let sweep: FrameView["sweep"] = null;
    if (this.previous) {
      const p = ((now - this.previous.since) * 1000) / SWEEP_MS;
      if (p >= 1) this.previous = null;
      else {
        const at = easeInOut(Math.max(0, p));
        sweep = { at, previous: this.lensView(this.previous.viewer, t, viewT, slot) };
      }
    }
    this.stage.render(lens.graphics, sweep ? { at: sweep.at, previous: sweep.previous.graphics } : undefined);

    return {
      t,
      viewT,
      clock: m.clock(t),
      score: m.score(t),
      playing: this.playing,
      rate: this.playing ? this.rate : 0,
      speed: this.speed,
      muted: this.muted,
      slot,
      replaySpeed,
      shot,
      forcedShot: this.forcedShot,
      lens,
      sweep,
      ended: m.ended && t >= m.end,
      live: this.feed
        ? { atEdge: this.following, behind: Math.max(0, this.feed.edge() - t), delay: this.feed.clock.lead }
        : null,
    };
  }

  private lensView(v: Viewer, t: number, viewT: number, slot: ReplaySlot | null): LensView {
    const m = this.match;
    const club = m.clubs.get(v.teamId);
    const accent = v.lens === "club" ? (club?.colours.primary ?? "#e84a5f") : LENS_ACCENT[v.lens];
    const box = boxAt(this.schedule(v), t);
    const tags: Tag[] = [];
    let graphics: LensGraphics = NO_GRAPHICS;
    let notInvolved = false;
    const cues = m.cues(v.lang);

    const tag = (id: string, major: boolean): Tag | null => {
      const p = m.players.get(id);
      const at = this.stage.projectPlayer(id, major ? 2.4 : 1.8);
      if (!p || !at) return null;
      return { playerId: id, name: p.short_name, shirt: p.shirt, color: p.club.colours.primary, x: at.x, y: at.y, major };
    };

    if (v.lens === "player") {
      const own = slot?.cues.find((c) => c.layer === "player" && c.player_id === v.playerId);
      const involved = !!own;
      if (slot && !involved) notInvolved = true;
      graphics = {
        ...NO_GRAPHICS,
        highlight: { playerId: v.playerId, color: accent },
        trail: slot && involved && own?.camera?.trail ? { slotId: slot.id, playerId: v.playerId } : null,
      };
      const main = tag(v.playerId, true);
      if (main) {
        if (slot && involved) {
          const tr = this.stage.trail(slot.id, v.playerId);
          if (tr) {
            main.speedKmh = this.match.tracks.speedAt(v.playerId, viewT);
            main.peakKmh = own?.camera?.speedo ?? tr.peakKmh;
          }
        }
        const badge = badgesAt(cues, v, t).find((c: Cue) => c.badge?.player_id === v.playerId);
        if (badge && !slot) main.badgeKmh = badge.badge!.speed_kmh;
        tags.push(main);
      }
    } else if (v.lens === "club") {
      graphics = { ...NO_GRAPHICS, clubGlow: { teamId: v.teamId, color: accent } };
    } else {
      graphics = { ...NO_GRAPHICS, ballTrail: slot ? { slotId: slot.id } : null };
    }

    // In replays, name the players the move ran through.
    if (slot) {
      const seen = new Set(tags.map((x) => x.playerId));
      for (const c of slot.cues) {
        if (c.layer !== "player" || !c.player_id || seen.has(c.player_id)) continue;
        seen.add(c.player_id);
        const minor = tag(c.player_id, false);
        if (minor) tags.push(minor);
      }
      if (slot.cues.every((c) => c.layer !== "player") && slot.cues[0]?.camera?.highlight) {
        const minor = tag(slot.cues[0].camera.highlight, false);
        if (minor && !seen.has(minor.playerId)) tags.push(minor);
      }
    }
    return { viewer: v, accent, graphics, box, tags: declutter(tags), notInvolved };
  }
}

/** The event a replay is about: the latest marker inside its window or just after. */
function markerFor(m: Match, slot: ReplaySlot): Marker | null {
  let best: Marker | null = null;
  for (const k of m.markers) if (k.t >= slot.window[0] && k.t <= slot.start + 0.5) best = k;
  return best;
}

/** Lifts name tags that would overlap, so players close together stay readable. */
function declutter(tags: Tag[]): Tag[] {
  const height = (t: Tag) => (t.speedKmh !== undefined ? 88 : t.badgeKmh !== undefined ? 46 : 22);
  const placed: Tag[] = [];
  for (const t of [...tags].sort((a, b) => Number(b.major) - Number(a.major) || b.y - a.y)) {
    let y = t.y;
    for (let i = 0; i < 6; i++) {
      const h = height(t);
      const hit = placed.find((p) => Math.abs(p.x - t.x) < 90 && y > p.y - height(p) && y - h < p.y);
      if (!hit) break;
      y = hit.y - height(hit) - 2;
    }
    placed.push({ ...t, y });
  }
  return placed;
}

function easeInOut(x: number) {
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}
