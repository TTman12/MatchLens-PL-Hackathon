import { PITCH_LENGTH_M, PITCH_WIDTH_M, type MatchMeta } from "../contracts";

/** Mirrors matchlens/contracts/pitch.py. */
export type Direction = "+x" | "-x";

export function attackingDirection(meta: MatchMeta, teamId: string, period: number): Direction {
  let d: Direction = meta.home_attacks_in_period_1;
  if (teamId !== meta.home.team_id) d = d === "+x" ? "-x" : "+x";
  if (period === 2) d = d === "+x" ? "-x" : "+x";
  return d;
}

/** Attacking-frame point (events) to the pitch frame (frames, graphics). */
export function toPitch(p: readonly unknown[], d: Direction): [number, number] {
  const x = p[0] as number;
  const y = p[1] as number;
  return d === "+x" ? [x, y] : [PITCH_LENGTH_M - x, PITCH_WIDTH_M - y];
}

/** Mirrors format_clock in matchlens/contracts/common.py. */
export function formatClock(t: number, period: number, periodStartT: number): string {
  const elapsed = Math.max(0, Math.floor(t - periodStartT));
  const base = 45 * (period - 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  if (elapsed < 2700) return `${base + Math.floor(elapsed / 60)}:${pad(elapsed % 60)}`;
  const extra = elapsed - 2700;
  return `${base + 45}+${Math.floor(extra / 60)}:${pad(extra % 60)}`;
}
