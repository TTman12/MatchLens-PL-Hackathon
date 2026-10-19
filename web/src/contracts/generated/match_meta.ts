/* Generated from schemas/match_meta.schema.json by web/scripts/gen-types.mjs. Do not edit. */

export type SchemaVersion = string;
export type MatchId = string;
export type LeagueId = string;
export type SeasonId = string;
export type Matchday = number;
/**
 * Simulator seed; null if hand-made
 */
export type Seed = number | null;
/**
 * ISO 8601 local date-time, fictional
 */
export type KickoffLocal = string;
export type Stadium = string;
export type Referee = string;
/**
 * e.g. clear, overcast, rain, wind
 */
export type Condition = string;
export type TemperatureC = number;
export type WindKmh = number;
export type TeamId = string;
export type Formation = string;
/**
 * @minItems 11
 * @maxItems 11
 */
export type Starting = [
  LineupEntry,
  LineupEntry,
  LineupEntry,
  LineupEntry,
  LineupEntry,
  LineupEntry,
  LineupEntry,
  LineupEntry,
  LineupEntry,
  LineupEntry,
  LineupEntry
];
export type PlayerId = string;
/**
 * Formation slot, e.g. GK, LCB, RW, ST
 */
export type Slot = string;
export type Bench = string[];
/**
 * Pitch-frame direction the home team attacks in period 1; swaps at half-time
 */
export type HomeAttacksInPeriod1 = "+x" | "-x";
export type Derby = boolean;
/**
 * Plain facts, e.g. 'Winner goes top'
 */
export type Notes = string[];
export type Home = number;
export type Draw = number;
export type Away = number;

/**
 * ``match.json``: one per match. Player attributes live in ``league.json``.
 */
export interface MatchMeta {
  schema_version: SchemaVersion;
  match_id: MatchId;
  league_id: LeagueId;
  season_id: SeasonId;
  matchday: Matchday;
  seed?: Seed;
  kickoff_local: KickoffLocal;
  stadium: Stadium;
  referee: Referee;
  weather: Weather;
  home: TeamSheet;
  away: TeamSheet;
  home_attacks_in_period_1: HomeAttacksInPeriod1;
  stakes?: Stakes;
  pre_match_win_prob: WinProbability;
}
export interface Weather {
  condition: Condition;
  temperature_c: TemperatureC;
  wind_kmh: WindKmh;
}
export interface TeamSheet {
  team_id: TeamId;
  formation: Formation;
  starting: Starting;
  bench?: Bench;
}
export interface LineupEntry {
  player_id: PlayerId;
  slot: Slot;
}
export interface Stakes {
  derby?: Derby;
  notes?: Notes;
}
/**
 * Three-way win probability from the home team's point of view. Sums to 1.
 */
export interface WinProbability {
  home: Home;
  draw: Draw;
  away: Away;
}
