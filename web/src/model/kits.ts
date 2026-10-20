import type { Club } from "../contracts";

/** Colours of a disc on the pitch: fill, rim and shirt number. */
export interface Kit {
  primary: string;
  secondary: string;
  text: string;
}

/** Goalkeeper shirts, as real keepers wear: loud colours no outfield kit uses. */
const KEEPER_KITS: Kit[] = [
  { primary: "#f2e530", secondary: "#1c1c1c", text: "#1c1c1c" }, // yellow
  { primary: "#3ee07a", secondary: "#0e3b1f", text: "#0e3b1f" }, // lime
  { primary: "#ff7a1f", secondary: "#2a1405", text: "#2a1405" }, // orange
  { primary: "#ff4fd8", secondary: "#3a0b31", text: "#ffffff" }, // pink
  { primary: "#25d7f2", secondary: "#06303a", text: "#06303a" }, // cyan
  { primary: "#9b6bff", secondary: "#1d0f3d", text: "#ffffff" }, // violet
];

function rgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Rough perceptual distance between two colours (weighted RGB). */
export function colourDistance(a: string, b: string): number {
  const [r1, g1, b1] = rgb(a);
  const [r2, g2, b2] = rgb(b);
  const r = (r1 + r2) / 2;
  const dr = r1 - r2;
  const dg = g1 - g2;
  const db = b1 - b2;
  return Math.sqrt((2 + r / 256) * dr * dr + 4 * dg * dg + (2 + (255 - r) / 256) * db * db);
}

/**
 * Goalkeeper kits for the home and away keepers: each the keeper colour that stands
 * furthest from both clubs' shirts (and from the other keeper), so a keeper never
 * blends into either team.
 */
export function keeperKits(home: Club, away: Club): [Kit, Kit] {
  const shirts = [home.colours.primary, home.colours.secondary, away.colours.primary, away.colours.secondary];
  const clash = (k: Kit, avoid: string[]) => Math.min(...avoid.map((c) => colourDistance(k.primary, c)));
  const ranked = [...KEEPER_KITS].sort((a, b) => clash(b, shirts) - clash(a, shirts));
  const first = ranked[0]!;
  const second = ranked.slice(1).sort((a, b) => clash(b, [...shirts, first.primary]) - clash(a, [...shirts, first.primary]))[0]!;
  return [first, second];
}
