import type { Frame } from "../contracts";

/**
 * Tracking data packed into typed arrays, so any player's position or speed at any
 * match time is a lookup and an interpolation. Everything the replays draw (trails,
 * speedometers, highlights) is derived from this, for every player, with no server call.
 */
export class Tracks {
  readonly times: Float64Array;
  readonly ball: Float32Array; // n * 3: x, y, z
  readonly players = new Map<string, Float32Array>(); // n * 4: x, y, vx, vy; NaN when off the pitch
  readonly start: number;
  readonly end: number;
  readonly dt: number;

  constructor(frames: Frame[]) {
    if (frames.length < 2) throw new Error("need at least two frames");
    const n = frames.length;
    this.times = new Float64Array(n);
    this.ball = new Float32Array(n * 3);
    const ids = new Set<string>();
    for (const f of frames) for (const id of Object.keys(f.players)) ids.add(id);
    for (const id of ids) this.players.set(id, new Float32Array(n * 4).fill(Number.NaN));

    frames.forEach((f, i) => {
      this.times[i] = f.t;
      const b = f.ball as number[];
      this.ball.set([b[0] ?? 0, b[1] ?? 0, b[2] ?? 0], i * 3);
      for (const [id, p] of Object.entries(f.players)) {
        this.players.get(id)!.set(p as number[], i * 4);
      }
    });
    this.start = this.times[0]!;
    this.end = this.times[n - 1]!;
    this.dt = (this.end - this.start) / (n - 1);
  }

  get length(): number {
    return this.times.length;
  }

  /** Frame index just before `t` and the blend toward the next one. Frames are evenly spaced. */
  locate(t: number): [number, number] {
    const n = this.times.length;
    const f = (Math.min(Math.max(t, this.start), this.end) - this.start) / this.dt;
    const i = Math.min(Math.floor(f), n - 2);
    return [i, f - i];
  }

  ballAt(t: number, out: [number, number, number]): [number, number, number] {
    const [i, a] = this.locate(t);
    const b = this.ball;
    for (let k = 0; k < 3; k++) out[k] = b[i * 3 + k]! * (1 - a) + b[(i + 1) * 3 + k]! * a;
    return out;
  }

  /** Pitch-frame position, or false if the player is not on the pitch at `t`. */
  playerAt(id: string, t: number, out: [number, number]): boolean {
    const p = this.players.get(id);
    if (!p) return false;
    const [i, a] = this.locate(t);
    const x0 = p[i * 4]!;
    const x1 = p[(i + 1) * 4]!;
    if (Number.isNaN(x0) || Number.isNaN(x1)) return false;
    out[0] = x0 * (1 - a) + x1 * a;
    out[1] = p[i * 4 + 1]! * (1 - a) + p[(i + 1) * 4 + 1]! * a;
    return true;
  }

  /** Speed in km/h from the frame velocities. */
  speedAt(id: string, t: number): number {
    const p = this.players.get(id);
    if (!p) return 0;
    const [i, a] = this.locate(t);
    const s0 = Math.hypot(p[i * 4 + 2]!, p[i * 4 + 3]!);
    const s1 = Math.hypot(p[(i + 1) * 4 + 2]!, p[(i + 1) * 4 + 3]!);
    const s = s0 * (1 - a) + s1 * a;
    return Number.isNaN(s) ? 0 : s * 3.6;
  }
}

/** Parses frames.jsonl text. */
export function parseFrames(text: string): Frame[] {
  const out: Frame[] = [];
  let at = 0;
  while (at < text.length) {
    let nl = text.indexOf("\n", at);
    if (nl === -1) nl = text.length;
    if (nl > at) out.push(JSON.parse(text.slice(at, nl)) as Frame);
    at = nl + 1;
  }
  return out;
}
