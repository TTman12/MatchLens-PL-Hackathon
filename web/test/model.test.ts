import { describe, expect, it } from "vitest";
import { boxAt, localise, scheduleBoxes, MAX_BOX_DELAY_S } from "../src/model/cues";
import { replayCameraFor, replayPlan, replayTime, slotAt } from "../src/model/replays";
import type { Viewer } from "../src/model/viewer";
import type { Cue } from "../src/contracts";
import { colourDistance, keeperKits } from "../src/model/kits";
import { sampleMatch } from "./sample";

const m = sampleMatch();
const viewer = (over: Partial<Viewer>): Viewer => ({ lens: "player", playerId: "ash-09", teamId: "ash", lang: "en", ...over });
const goal = () => m.slots.find((s) => s.momentId === "m017-mo02")!;

describe("tracks", () => {
  it("interpolates between frames", () => {
    const a: [number, number] = [0, 0];
    const b: [number, number] = [0, 0];
    const c: [number, number] = [0, 0];
    m.tracks.playerAt("ash-09", 50, a);
    m.tracks.playerAt("ash-09", 50.1, b);
    m.tracks.playerAt("ash-09", 50.05, c);
    expect(c[0]).toBeCloseTo((a[0] + b[0]) / 2, 5);
  });

  it("reproduces the agents' peak speed from the frames alone", () => {
    const trail = m.trails.get(goal().id)!.get("ash-09")!;
    expect(trail.peakKmh).toBeCloseTo(34.3, 0);
    expect(trail.distanceM).toBeCloseTo(77.5, 0);
  });

  it("has a trail for every player on the pitch in every replay", () => {
    for (const s of m.slots) expect(m.trails.get(s.id)!.size).toBe(22);
  });
});

describe("replays", () => {
  it("groups the goal's per-lens variants into one slot", () => {
    const s = goal();
    expect(s.shot).toBe("spidercam_goal");
    expect(s.cues.map((c) => c.player_id ?? c.layer).sort()).toEqual(["ash-06", "ash-08", "ash-09", "global"]);
  });

  it("plays the build-up quick and the finish in slow motion, ending on the goal", () => {
    const s = goal();
    const plan = replayPlan(s);
    expect(plan.slowSpeed).toBe(0.5);
    expect(s.window[1] - plan.slowFrom).toBeGreaterThanOrEqual(3);
    expect(replayTime(s, s.start).t).toBe(s.window[0]);
    expect(replayTime(s, s.end - 1e-9).t).toBeCloseTo(s.window[1], 5);
  });

  it("holds the last frame when the window fits at replay speed", () => {
    const short = { ...goal(), window: [50, 52] as [number, number] };
    expect(replayTime(short, short.start + 10).t).toBe(52);
  });

  it("switches the highlighted player instantly, falling back to the global replay", () => {
    const s = goal();
    expect(replayCameraFor(s, viewer({ playerId: "ash-08" }))?.highlight).toBe("ash-08");
    expect(replayCameraFor(s, viewer({ playerId: "ash-09" }))?.speedo).toBe(34.3);
    expect(replayCameraFor(s, viewer({ playerId: "brk-04" }))?.highlight).toBeFalsy();
  });

  it("only shows a lens-only replay to that lens", () => {
    const t = 135;
    expect(slotAt(m.slots, t, viewer({ lens: "club", teamId: "ash" }))?.shot).toBe("card_close");
    expect(slotAt(m.slots, t, viewer({ lens: "club", teamId: "brk" }))).toBeNull();
    expect(slotAt(m.slots, t, viewer({ lens: "pundit" }))).toBeNull();
  });
});

describe("cues", () => {
  it("picks the viewer's language and falls back to English", () => {
    const es = localise(m.cueTrack.cues, "es");
    const box = (cues: Cue[], pid: string) => cues.find((c) => c.template === "fact_box" && c.player_id === pid)!;
    expect(box(es, "ash-09").lang).toBe("es");
    expect(box(es, "ash-08").lang).toBe("en");
    expect(localise(m.cueTrack.cues, "en").filter((c) => c.lang === "es")).toHaveLength(0);
  });

  it("gives each viewer their own box for the goal", () => {
    const at = 75;
    const show = (v: Viewer) => boxAt(scheduleBoxes(m.cues(v.lang), v), at);
    expect(show(viewer({ playerId: "ash-09" }))?.cue?.cue_id).toBe("m017-c008");
    expect(show(viewer({ playerId: "ash-08" }))?.cue?.cue_id).toBe("m017-c009");
    expect(show(viewer({ playerId: "ash-09", lang: "es" }))?.cue?.cue_id).toBe("m017-c011");
    expect(show(viewer({ lens: "club", teamId: "ash" }))?.cue?.cue_id).toBe("m017-c007");
    expect(show(viewer({ lens: "club", teamId: "brk" }))).toBeNull();
    expect(show(viewer({ lens: "pundit" }))?.cue?.cue_id).toBe("m017-c012");
  });

  it("tells a viewer whose player wasn't involved, instead of inventing a box", () => {
    const b = boxAt(scheduleBoxes(m.cues("en"), viewer({ playerId: "brk-04" })), 74);
    expect(b?.cue).toBeNull();
    expect(b?.notInvolved?.momentId).toBe("m017-mo02");
  });

  it("never shows two boxes at once", () => {
    const base: Cue = m.cueTrack.cues.find((c) => c.cue_id === "m017-c012")!;
    const crowded: Cue[] = [0, 1, 2, 3].map((i) => ({ ...base, cue_id: `m017-c9${i}0`, t_show: 100 + i, priority: i / 10 }));
    const s = scheduleBoxes(crowded, viewer({ lens: "pundit" }));
    for (let i = 1; i < s.length; i++) expect(s[i]!.start).toBeGreaterThanOrEqual(s[i - 1]!.end);
    for (const b of s) expect(b.start - b.cue!.t_show).toBeLessThanOrEqual(MAX_BOX_DELAY_S);
    expect(s.length).toBeLessThan(crowded.length);
  });
});

describe("match", () => {
  it("keeps score and the broadcast clock", () => {
    expect(m.score(58)).toEqual([0, 0]);
    expect(m.score(60)).toEqual([1, 0]);
    expect(m.clock(131)).toBe("2:11");
  });

  it("finds the moments to mark on the scrubber", () => {
    expect(m.markers.map((k) => k.kind)).toEqual(["corner", "goal", "card"]);
    // Brackenford attack -x in the first half, so their corner is at the left end.
    expect(m.markers[0]!.at[0]).toBeLessThan(1);
  });
});

describe("keeper kits", () => {
  it("dresses each keeper in a colour far from both teams and from each other", () => {
    const [home, away] = keeperKits(m.home, m.away);
    expect(home.primary).not.toBe(away.primary);
    for (const kit of [home, away]) {
      for (const shirt of [m.home.colours.primary, m.away.colours.primary]) {
        expect(colourDistance(kit.primary, shirt)).toBeGreaterThan(150);
      }
    }
  });
});
