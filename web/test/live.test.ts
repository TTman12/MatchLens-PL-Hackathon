import { describe, expect, it } from "vitest";
import type { CueTrack, Frame, League, MatchEvent, MatchMeta } from "../src/contracts";
import { MAX_RATE, rateAt, slowSpans, type MomentTiming } from "../src/model/clock";
import { Match } from "../src/model/match";
import { parseFrames, Tracks } from "../src/model/tracks";
import { read, readJson, sampleMatch } from "./sample";

const full = sampleMatch();
const moments = readJson<MomentTiming[]>("moments.json");

describe("condensed clock", () => {
  const spans = slowSpans(moments, full.cueTrack.cues);

  it("plays every replay and fact box at real time", () => {
    for (const c of full.cueTrack.cues) {
      if (c.template !== "replay" && c.template !== "fact_box") continue;
      expect(rateAt(c.t_show, spans)).toBe(1);
      expect(rateAt(c.t_show + c.duration - 0.01, spans)).toBe(1);
    }
  });

  it("starts slowing before a moment and is at full speed well away from one", () => {
    const first = spans[0]!;
    expect(rateAt(first.start - 5, spans)).toBeGreaterThan(1);
    expect(rateAt(first.start - 5, spans)).toBeLessThan(MAX_RATE);
    expect(rateAt(first.end + 200, spans)).toBeCloseTo(MAX_RATE);
  });

  it("is what the match uses", () => {
    const m = new Match(full.meta, full.league, full.events, full.cueTrack, full.tracks, moments);
    expect(m.spans).toEqual(spans);
  });
});

describe("live match", () => {
  const frames = parseFrames(read("frames.jsonl"));
  const events = readJson<MatchEvent[]>("events.json");
  const cues = readJson<CueTrack>("cues.json");

  /** The sample delivered in pieces, as a live feed would, cut at `cuts` (match seconds). */
  function streamed(cuts: number[]): Match {
    const upto = <T extends { t: number }>(xs: T[], a: number, b: number) => xs.filter((x) => x.t > a && x.t <= b);
    const cueUpto = (a: number, b: number) => cues.cues.filter((c) => c.t_show > a && c.t_show <= b);
    const first = cuts[0]!;
    const m = new Match(
      readJson<MatchMeta>("match.json"),
      readJson<League>("league.json"),
      upto(events, -1, first),
      { ...cues, cues: cueUpto(-1, first) },
      new Tracks(upto<Frame>(frames, -1, first)),
      [],
      true,
    );
    for (let i = 1; i < cuts.length; i++) {
      const [a, b] = [cuts[i - 1]!, cuts[i]!];
      m.extend({ frames: upto<Frame>(frames, a, b), events: upto(events, a, b), cues: cueUpto(a, b) });
    }
    return m;
  }

  it("ends up the same as the match loaded whole", () => {
    const m = streamed([10, 40, 41, 95, 180]);
    expect(m.tracks.length).toBe(full.tracks.length);
    expect(m.end).toBe(full.end);
    expect(m.markers).toEqual(full.markers);
    expect(m.slots.map((s) => s.id)).toEqual(full.slots.map((s) => s.id));
    const goal = full.slots.find((s) => s.momentId === "m017-mo02")!;
    expect(m.trails.get(goal.id)!.get("ash-09")!.peakKmh).toBeCloseTo(full.trails.get(goal.id)!.get("ash-09")!.peakKmh, 6);
    const a: [number, number] = [0, 0];
    const b: [number, number] = [0, 0];
    m.tracks.playerAt("brk-04", 123.45, a);
    full.tracks.playerAt("brk-04", 123.45, b);
    expect(a).toEqual(b);
  });

  it("counts versions and draws against a full match's length until it ends", () => {
    const m = streamed([10, 40]);
    expect(m.version).toBe(2);
    expect(m.horizon).toBeGreaterThan(90 * 60);
    m.ended = true;
    expect(m.horizon).toBe(m.end);
  });

  it("keeps a substitute off the pitch before their first frame", () => {
    const head = frames.slice(0, 50);
    const tail: Frame[] = frames.slice(50, 60).map((f) => ({ ...f, players: { ...f.players, "ash-14": [50, 30, 0, 0] } }));
    const t = new Tracks(head);
    t.append(tail);
    const p: [number, number] = [0, 0];
    expect(t.playerAt("ash-14", frames[10]!.t, p)).toBe(false);
    expect(t.playerAt("ash-14", frames[55]!.t, p)).toBe(true);
    expect(t.length).toBe(60);
  });
});
