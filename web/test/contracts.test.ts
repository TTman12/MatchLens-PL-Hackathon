import { readFileSync } from "node:fs";
import path from "node:path";
import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";
import { read, readJson, schemaDir } from "./sample";

// The player reads data only through the shared contracts. These checks make sure the
// files it is built against still match the schemas its types were generated from.
const ajv = new Ajv2020({ allErrors: true, strict: false });
const schema = (name: string) =>
  ajv.compile(JSON.parse(readFileSync(path.join(schemaDir, `${name}.schema.json`), "utf8")));

describe("sample data matches the shared schemas", () => {
  it.each([
    ["match.json", "match_meta"],
    ["league.json", "league"],
    ["cues.json", "cue_track"],
  ])("%s", (file, name) => {
    const validate = schema(name);
    expect(validate(readJson(file)), JSON.stringify(validate.errors)).toBe(true);
  });

  it("events.json", () => {
    const validate = schema("match_event");
    for (const e of readJson<unknown[]>("events.json")) expect(validate(e), JSON.stringify(validate.errors)).toBe(true);
  });

  it("frames.jsonl", () => {
    const validate = schema("frame");
    const lines = read("frames.jsonl").trim().split("\n");
    for (const line of lines.filter((_, i) => i % 50 === 0)) expect(validate(JSON.parse(line))).toBe(true);
  });
});
