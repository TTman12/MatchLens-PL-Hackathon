import type { Tracks } from "./tracks";
import type { ReplaySlot } from "./replays";

/** One player's path and speed through a replay window, sampled at the frame rate. */
export interface Trail {
  playerId: string;
  /** x, y in the pitch frame and t in match time, per sample. */
  points: Float32Array;
  speeds: Float32Array; // km/h per sample
  peakKmh: number;
  peakT: number;
  distanceM: number;
}

/**
 * Trails for every player on the pitch during a replay window. Computed once at load
 * from the frames the browser already has: no model calls, and switching favourite
 * player only changes which precomputed trail is drawn.
 */
export function trailsFor(tracks: Tracks, window: [number, number]): Map<string, Trail> {
  const [w0, w1] = window;
  const n = Math.max(2, Math.round((w1 - w0) / tracks.dt) + 1);
  const out = new Map<string, Trail>();
  const pos: [number, number] = [0, 0];
  for (const id of tracks.players.keys()) {
    const points = new Float32Array(n * 3);
    const speeds = new Float32Array(n);
    let peak = 0;
    let peakT = w0;
    let dist = 0;
    let ok = true;
    for (let i = 0; i < n; i++) {
      const t = w0 + ((w1 - w0) * i) / (n - 1);
      if (!tracks.playerAt(id, t, pos)) {
        ok = false;
        break;
      }
      if (i > 0) dist += Math.hypot(pos[0] - points[(i - 1) * 3]!, pos[1] - points[(i - 1) * 3 + 1]!);
      points.set([pos[0], pos[1], t], i * 3);
      const s = tracks.speedAt(id, t);
      speeds[i] = s;
      if (s > peak) {
        peak = s;
        peakT = t;
      }
    }
    if (ok) out.set(id, { playerId: id, points, speeds, peakKmh: peak, peakT, distanceM: dist });
  }
  return out;
}

export type SlotTrails = Map<string, Map<string, Trail>>;

export function allTrails(tracks: Tracks, slots: ReplaySlot[]): SlotTrails {
  return new Map(slots.map((s) => [s.id, trailsFor(tracks, s.window)]));
}
