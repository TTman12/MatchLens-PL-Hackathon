import type { Cue } from "../contracts";
import { matchesViewer, type Viewer } from "./viewer";

/**
 * Picks one language for each cue. The track holds one cue per language; a cue missing
 * in the viewer's language falls back to English, then to whatever exists.
 */
export function localise(cues: Cue[], lang: string): Cue[] {
  const groups = new Map<string, Cue[]>();
  for (const c of cues) {
    const key = [c.moment_id, c.t_show, c.layer, c.template, c.player_id, c.team_id].join("|");
    const g = groups.get(key);
    if (g) g.push(c);
    else groups.set(key, [c]);
  }
  const out: Cue[] = [];
  for (const g of groups.values()) {
    const pick =
      g.find((c) => (c.lang ?? "en") === lang) ?? g.find((c) => (c.lang ?? "en") === "en") ?? g[0]!;
    out.push(pick);
  }
  return out.sort((a, b) => a.t_show - b.t_show);
}

export interface ScheduledBox {
  key: string;
  cue: Cue | null; // null for a browser-made "not involved" line
  start: number;
  end: number;
  notInvolved?: { playerId: string; momentId: string };
}

/** How long a box may wait behind another before it is stale and dropped. */
export const MAX_BOX_DELAY_S = 6;
const NOT_INVOLVED_S = 4;

/**
 * The one-box-at-a-time rule. Boxes for this viewer are taken in time order (higher
 * priority first when they share a time); a box that arrives while another is up waits
 * for it to finish, and is dropped if that would make it more than MAX_BOX_DELAY_S late.
 *
 * In the Player lens, a moment that has Player boxes but none for the selected player
 * gets a short "not involved" line instead (contracts: the browser makes these itself).
 */
export function scheduleBoxes(cues: Cue[], v: Viewer): ScheduledBox[] {
  type Candidate = Omit<ScheduledBox, "start" | "end"> & { t: number; duration: number; priority: number };
  const candidates: Candidate[] = [];

  for (const c of cues) {
    if ((c.template === "fact_box" || c.template === "brief") && matchesViewer(c, v)) {
      candidates.push({ key: c.cue_id, cue: c, t: c.t_show, duration: c.duration, priority: c.priority ?? 0 });
    }
  }

  if (v.lens === "player") {
    const firstPlayerBox = new Map<string, Cue>();
    const selectedHas = new Set<string>();
    for (const c of cues) {
      if (c.layer !== "player" || !c.moment_id) continue;
      if (c.player_id === v.playerId) selectedHas.add(c.moment_id);
      if (c.template === "fact_box" && !firstPlayerBox.has(c.moment_id)) firstPlayerBox.set(c.moment_id, c);
    }
    for (const [momentId, c] of firstPlayerBox) {
      if (selectedHas.has(momentId)) continue;
      candidates.push({
        key: `not-involved:${momentId}`,
        cue: null,
        notInvolved: { playerId: v.playerId, momentId },
        t: c.t_show,
        duration: NOT_INVOLVED_S,
        priority: 0,
      });
    }
  }

  candidates.sort((a, b) => a.t - b.t || b.priority - a.priority);
  const out: ScheduledBox[] = [];
  let free = -Infinity;
  for (const c of candidates) {
    const start = Math.max(c.t, free);
    if (start - c.t > MAX_BOX_DELAY_S) continue;
    const { t: _t, duration, priority: _p, ...rest } = c;
    out.push({ ...rest, start, end: start + duration });
    free = start + duration;
  }
  return out;
}

export function boxAt(schedule: ScheduledBox[], t: number): ScheduledBox | null {
  for (const b of schedule) {
    if (t >= b.start && t < b.end) return b;
    if (b.start > t) break;
  }
  return null;
}

/** Speed badges for this viewer that are up at `t`. */
export function badgesAt(cues: Cue[], v: Viewer, t: number): Cue[] {
  return cues.filter(
    (c) => c.template === "speed_badge" && t >= c.t_show && t < c.t_show + c.duration && matchesViewer(c, v),
  );
}

/** Rail items (below the on-screen threshold) this viewer sees, up to `t`. */
export function railItems(cues: Cue[], v: Viewer): Cue[] {
  return cues.filter((c) => c.template === "timeline_item" && matchesViewer(c, v));
}
