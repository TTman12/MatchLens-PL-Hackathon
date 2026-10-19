import type { Cue } from "../contracts";

/**
 * The condensed clock (build plan 3.10), mirroring matchlens/api/clock.py. Between
 * moments playback runs fast; it eases down to real time a little before every moment
 * that matters, plays the build-up, replay and fact box at 1x, then eases back up. The
 * speed is a function of match time alone, so it is the same for every lens and
 * favourite, and switching never makes the clock jump.
 */
export const CLOCK_SLOWDOWN_IMPORTANCE = 0.3;
export const MAX_RATE = 30;
const LEAD_IN_S = 12;
const TAIL_S = 8;
const EASE_S = 20;
const MERGE_GAP_S = 15;
const SLOW_TEMPLATES = new Set(["replay", "fact_box", "brief"]);

/** The parts of a moment the clock needs (the live feed sends just these). */
export interface MomentTiming {
  moment_id: string;
  t_start: number;
  t_end: number;
  replay_window: [number, number] | number[];
  importance: number;
}

export interface Span {
  start: number;
  end: number;
}

/**
 * Stretches of match time that play at 1x. A moment is slow from its lead-in to the end
 * of its last replay or box when it has either, or when the detector scored it above the
 * threshold (its cues may still be on their way, so it keeps a short tail). Briefs, and
 * boxes for moments not listed, are slow too.
 */
export function slowSpans(moments: MomentTiming[], cues: Cue[]): Span[] {
  const ends = new Map<string, number>();
  const spans: Span[] = [];
  for (const c of cues) {
    if (!SLOW_TEMPLATES.has(c.template)) continue;
    const end = c.t_show + c.duration;
    if (c.template === "brief" || !c.moment_id) spans.push({ start: c.t_show - 2, end });
    else {
      ends.set(c.moment_id, Math.max(ends.get(c.moment_id) ?? end, end));
      spans.push({ start: c.t_show - LEAD_IN_S, end });
    }
  }
  for (const m of moments) {
    if (m.importance < CLOCK_SLOWDOWN_IMPORTANCE && !ends.has(m.moment_id)) continue;
    const start = Math.min(m.t_start, m.replay_window[0] ?? m.t_start) - LEAD_IN_S;
    spans.push({ start, end: Math.max(m.t_end + TAIL_S, ends.get(m.moment_id) ?? 0) });
  }
  return merge(spans);
}

function merge(spans: Span[]): Span[] {
  const out: Span[] = [];
  for (const s of [...spans].sort((a, b) => a.start - b.start)) {
    const last = out.at(-1);
    if (last && s.start - last.end < MERGE_GAP_S) last.end = Math.max(last.end, s.end);
    else out.push({ ...s });
  }
  return out;
}

/** Playback speed at match time `t`: 1 inside a slow span, easing up to `maxRate`. */
export function rateAt(t: number, spans: Span[], maxRate = MAX_RATE): number {
  let d = Infinity;
  for (const s of spans) {
    if (t >= s.start && t <= s.end) return 1;
    d = Math.min(d, Math.abs(s.start - t), Math.abs(t - s.end));
  }
  const x = Math.min(1, d / EASE_S);
  return 1 + (maxRate - 1) * x * x * (3 - 2 * x);
}
