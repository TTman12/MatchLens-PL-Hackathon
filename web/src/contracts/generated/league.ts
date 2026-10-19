/* Generated from schemas/league.schema.json by web/scripts/gen-types.mjs. Do not edit. */

export type SchemaVersion = string;
export type LeagueId = string;
export type Name = string;
export type TeamId = string;
export type Name1 = string;
export type ShortName = string;
export type City = string;
export type Stadium = string;
export type Primary = string;
export type Secondary = string;
/**
 * Shirt number colour, readable on primary
 */
export type Text = string;
/**
 * Pre-match team strength
 */
export type Rating = number;
/**
 * Default formation, e.g. 4-3-3
 */
export type Formation = string;
export type RivalIds = string[];
export type PlayerId = string;
export type Name2 = string;
/**
 * Name shown on name tags, e.g. a surname
 */
export type ShortName1 = string;
export type Shirt = number;
export type Position = "GK" | "DF" | "MF" | "FW";
/**
 * Detailed role, e.g. CB, LW, DM, ST
 */
export type Role = string;
export type Foot = "left" | "right" | "both";
export type TopSpeedKmh = number;
export type Pace = number;
export type Acceleration = number;
export type Passing = number;
export type Vision = number;
export type Finishing = number;
export type Tackling = number;
export type Keeping = number;
export type Discipline = number;
export type Stamina = number;
export type Squad = Player[];
export type Clubs = Club[];

/**
 * ``league.json``: the fixed universe a season is played in.
 */
export interface League {
  schema_version: SchemaVersion;
  league_id: LeagueId;
  name: Name;
  clubs: Clubs;
}
export interface Club {
  team_id: TeamId;
  name: Name1;
  short_name: ShortName;
  city: City;
  stadium: Stadium;
  colours: Colours;
  rating: Rating;
  formation: Formation;
  rival_ids?: RivalIds;
  squad: Squad;
}
export interface Colours {
  primary: Primary;
  secondary: Secondary;
  text: Text;
}
export interface Player {
  player_id: PlayerId;
  name: Name2;
  short_name: ShortName1;
  shirt: Shirt;
  position: Position;
  role: Role;
  foot: Foot;
  top_speed_kmh: TopSpeedKmh;
  attributes: Attributes;
}
/**
 * Player ratings the simulator draws on, 1 to 99.
 */
export interface Attributes {
  pace: Pace;
  acceleration: Acceleration;
  passing: Passing;
  vision: Vision;
  finishing: Finishing;
  tackling: Tackling;
  keeping: Keeping;
  discipline: Discipline;
  stamina: Stamina;
}
