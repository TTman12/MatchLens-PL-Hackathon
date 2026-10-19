import type { Camera, CameraShot, Cue } from "../contracts";
import { matchesViewer, type Viewer } from "./viewer";

/**
 * A replay slot on the playback timeline: from `start` to `end` of match time the screen
 * shows the replay window instead of live play. The cues in it are the per-lens and
 * per-player variants of the same replay; which one a viewer gets is picked locally, so
 * switching favourite player mid-replay swaps the highlight on the next frame.
 */
export interface ReplaySlot {
  id: string;
  momentId: string | null;
  start: number;
  end: number;
  window: [number, number];
  speed: number;
  shot: CameraShot;
  cues: Cue[];
}

export function replaySlots(cues: Cue[]): ReplaySlot[] {
  const slots = new Map<string, ReplaySlot>();
  for (const c of cues) {
    if (c.template !== "replay" || !c.camera?.replay) continue;
    const key = `${c.moment_id}|${c.t_show}`;
    const window = c.camera.replay as [number, number];
    const slot = slots.get(key);
    if (slot) {
      slot.cues.push(c);
      slot.end = Math.max(slot.end, c.t_show + c.duration);
    } else {
      slots.set(key, {
        id: key,
        momentId: c.moment_id ?? null,
        start: c.t_show,
        end: c.t_show + c.duration,
        window,
        speed: c.camera.replay_speed ?? 0.5,
        shot: c.camera.shot,
        cues: [c],
      });
    }
  }
  return [...slots.values()].sort((a, b) => a.start - b.start);
}

/** The variant of a replay this viewer sees: their lens's cue, else the global one. */
export function replayCameraFor(slot: ReplaySlot, v: Viewer): Camera | null {
  const own = slot.cues.find((c) => c.layer !== "global" && matchesViewer(c, v));
  const global = slot.cues.find((c) => c.layer === "global");
  return (own ?? global)?.camera ?? null;
}

/** Does any variant of this replay exist for this viewer? */
export function slotVisibleTo(slot: ReplaySlot, v: Viewer): boolean {
  return slot.cues.some((c) => matchesViewer(c, v));
}

export function slotAt(slots: ReplaySlot[], t: number, v: Viewer): ReplaySlot | null {
  for (const s of slots) if (t >= s.start && t < s.end && slotVisibleTo(s, v)) return s;
  return null;
}

/**
 * Maps playback time inside a slot to match time inside the replay window.
 *
 * If the whole window fits at the replay speed, it plays slowed throughout and holds
 * the last frame. Otherwise it plays like a broadcast replay: the build-up runs quick,
 * then the decisive end of the move plays at the replay speed. The fast part runs at 2x
 * when that leaves at least 3 s of slow motion, else the slow part takes half the slot.
 */
export function replayPlan(slot: Pick<ReplaySlot, "start" | "end" | "window" | "speed">) {
  const D = slot.end - slot.start;
  const [w0, w1] = slot.window;
  const W = w1 - w0;
  const rs = slot.speed;
  if (W / rs <= D) return { fastSpeed: rs, slowFrom: w0, slowSpeed: rs, fastFor: 0 };
  let fast = 2;
  let slowLen = (D - W / fast) / (1 / rs - 1 / fast);
  if (!(slowLen >= Math.min(3, W))) {
    slowLen = Math.min(W, (D * rs) / 2);
    fast = (W - slowLen) / (D - slowLen / rs);
  }
  const fastFor = (W - slowLen) / fast;
  return { fastSpeed: fast, slowFrom: w1 - slowLen, slowSpeed: rs, fastFor };
}

export function replayTime(slot: ReplaySlot, t: number): { t: number; speed: number } {
  const plan = replayPlan(slot);
  const u = Math.max(0, t - slot.start);
  const [w0, w1] = slot.window;
  if (u < plan.fastFor) return { t: w0 + u * plan.fastSpeed, speed: plan.fastSpeed };
  const tt = plan.slowFrom + (u - plan.fastFor) * plan.slowSpeed;
  return { t: Math.min(tt, w1), speed: tt >= w1 ? 0 : plan.slowSpeed };
}
