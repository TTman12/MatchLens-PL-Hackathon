import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { CueTrack, League, MatchEvent, MatchMeta } from "../src/contracts";
import { Match } from "../src/model/match";
import { parseFrames, Tracks } from "../src/model/tracks";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
export const sampleDir = path.join(root, "data/sample");
export const schemaDir = path.join(root, "schemas");

export const read = (file: string) => readFileSync(path.join(sampleDir, file), "utf8");
export const readJson = <T>(file: string) => JSON.parse(read(file)) as T;

let cached: Match | null = null;

/** The foundation's sample match, loaded the same way the browser loads it. */
export function sampleMatch(): Match {
  cached ??= new Match(
    readJson<MatchMeta>("match.json"),
    readJson<League>("league.json"),
    readJson<MatchEvent[]>("events.json"),
    readJson<CueTrack>("cues.json"),
    new Tracks(parseFrames(read("frames.jsonl"))),
  );
  return cached;
}
