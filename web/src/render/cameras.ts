import type { CameraShot } from "../contracts";
import type { Direction } from "../model/pitch";

/** A camera pose in the pitch frame: x along, y across (0 = near touchline), z up. */
export interface Pose {
  pos: [number, number, number];
  look: [number, number, number];
  fov: number;
}

export interface ShotContext {
  ball: [number, number, number];
  /** Smoothed ball, so the camera doesn't jitter with every touch. */
  follow: [number, number];
  /** The goal the featured team attacks. */
  attacking: Direction;
  /** Where the action is: the highlighted player, or the event location. */
  focus: [number, number];
  /** Seconds into the shot, for slow camera moves. */
  u: number;
  /** A player the shot should keep in frame, such as the viewer's favourite in a replay. */
  keep?: [number, number];
}

const L = 105;
const W = 68;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;

/** Camera presets (build plan 3.7). Each is a pure function of the shot context. */
export function poseFor(shot: CameraShot, c: ShotContext): Pose {
  const s = c.attacking === "+x" ? 1 : -1;
  const goalX = s > 0 ? L : 0;
  switch (shot) {
    case "tv_main": {
      // Elevated on the halfway line, panning to follow the play.
      const lx = clamp(c.follow[0], 14, L - 14);
      const ly = lerp(W / 2, c.follow[1], 0.45);
      // Zoom in a touch as play moves toward the far touchline.
      const fov = lerp(22, 18, clamp((ly - 20) / 40, 0, 1));
      return { pos: [L / 2 + (lx - L / 2) * 0.25, -52, 30], look: [lx, ly, 0], fov };
    }
    case "spidercam_goal": {
      // Flies behind the attack, facing the goal it is heading for.
      const bx = c.follow[0];
      const ideal = s > 0 ? Math.min(bx - 17, L - 34) : Math.max(bx + 17, 34);
      let camX = ideal;
      // Pull back and up so a trailing favourite stays in shot: the lens never loses them.
      if (c.keep) camX = s > 0 ? Math.max(Math.min(camX, c.keep[0] - 24), bx - 55) : Math.min(Math.max(camX, c.keep[0] + 24), bx + 55);
      const pull = Math.abs(ideal - camX);
      const camY = lerp(W / 2, c.follow[1], 0.55);
      const lookX = s > 0 ? Math.min(bx + 12, L - 4) - pull * 0.4 : Math.max(bx - 12, 4) + pull * 0.4;
      return { pos: [camX, camY, 13 + pull * 0.45], look: [lookX, lerp(c.follow[1], W / 2, 0.35), 0], fov: 52 };
    }
    case "corner_low": {
      // Low, behind the goal line, looking out at the box.
      const side = c.focus[1] < W / 2 ? -1 : 1;
      return {
        pos: [goalX + s * 7.5, W / 2 + side * 3, 3.2],
        look: [goalX - s * 13, W / 2 - side * 2, 0.6],
        fov: 56,
      };
    }
    case "card_close": {
      // Tight on the incident with a slow drift, like a referee close-up.
      const [fx, fy] = c.focus;
      const ang = -Math.PI / 2 + 0.35 + c.u * 0.025;
      return {
        pos: [fx + Math.cos(ang) * 17, fy + Math.sin(ang) * 17, 8],
        look: [fx, fy, 0.6],
        fov: 32,
      };
    }
    case "save_reverse": {
      // Keeper height, from behind the goal, looking back up the pitch.
      return {
        pos: [goalX + s * 4.5, lerp(W / 2, c.follow[1], 0.2), 1.9],
        look: [c.ball[0], c.ball[1], 0.8],
        fov: 50,
      };
    }
    case "tactical_high": {
      // High reverse angle from the far side, to show the lanes.
      return { pos: [c.focus[0], W + 34, 46], look: [c.focus[0], W / 2, 0], fov: 46 };
    }
  }
}

export const SHOT_LABELS: Record<CameraShot, string> = {
  tv_main: "Main camera",
  spidercam_goal: "Spider-cam",
  corner_low: "Corner cam",
  card_close: "Close-up",
  save_reverse: "Reverse angle",
  tactical_high: "Tactical cam",
};
