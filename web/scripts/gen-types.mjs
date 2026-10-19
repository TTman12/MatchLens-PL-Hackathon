// Generates TypeScript types from the shared JSON Schemas in ../schemas.
// Run `npm run gen:types` after a contract change; CI checks the output is current.
import { compileFromFile } from "json-schema-to-typescript";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const schemas = path.resolve(here, "../../schemas");
const out = path.resolve(here, "../src/contracts/generated");

// The files the player reads, each compiled on its own so names stay predictable.
const files = ["cue_track", "frame", "match_meta", "league", "match_event", "moment"];

const check = process.argv.includes("--check");
let stale = 0;
for (const name of files) {
  const ts = await compileFromFile(path.join(schemas, `${name}.schema.json`), {
    bannerComment: `/* Generated from schemas/${name}.schema.json by web/scripts/gen-types.mjs. Do not edit. */`,
    additionalProperties: false,
    style: { singleQuote: false },
  });
  const target = path.join(out, `${name}.ts`);
  if (check) {
    const current = await readFile(target, "utf8").catch(() => "");
    if (current !== ts) {
      console.error(`stale: ${path.relative(process.cwd(), target)}`);
      stale++;
    }
  } else {
    await writeFile(target, ts);
  }
}
if (stale) process.exit(1);
