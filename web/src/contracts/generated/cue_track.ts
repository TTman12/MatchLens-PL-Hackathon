/* Generated from schemas/cue_track.schema.json by web/scripts/gen-types.mjs. Do not edit. */

export type SchemaVersion = string;
export type MatchId = string;
export type Languages = string[];
export type CueId = string;
export type MatchId1 = string;
export type MomentId = string | null;
export type TShow = number;
/**
 * Seconds of playback the cue stays up
 */
export type Duration = number;
/**
 * Which overlay layer a cue belongs to. The lens sweep swaps the three lens layers.
 */
export type Layer = "global" | "player" | "club" | "pundit";
export type Template = "fact_box" | "not_involved" | "speed_badge" | "name_tag" | "replay" | "timeline_item" | "brief";
export type Lang = string;
/**
 * Required on the player layer
 */
export type PlayerId = string | null;
/**
 * Required on the club layer
 */
export type TeamId = string | null;
/**
 * Importance x relevance
 */
export type Priority = number;
export type Headline = string;
/**
 * One or two plain sentences
 */
export type Body = string;
export type Id = string;
export type ClaimType = "stat" | "season" | "table" | "fixture" | "discipline" | "win_prob" | "milestone";
/**
 * Human-readable statement of the fact
 */
export type Value = string;
/**
 * An event id or a context ref, e.g. season:ash-09:goals
 */
export type Source = string;
export type Evidence = EvidenceItem[];
export type EventIds = string[];
export type PassMap = [unknown, unknown, unknown, unknown][];
export type Notes = string[];
/**
 * Camera presets (build plan 3.7).
 */
export type CameraShot = "tv_main" | "spidercam_goal" | "corner_low" | "card_close" | "save_reverse" | "tactical_high";
/**
 * Match-time window
 */
export type Replay = [unknown, unknown] | null;
export type ReplaySpeed = number;
export type Highlight = string | null;
export type Trail = boolean;
/**
 * Peak speed shown, km/h
 */
export type Speedo = number | null;
/**
 * Pitch-frame point to frame on
 */
export type Focus = [unknown, unknown] | null;
export type PlayerId1 = string;
export type SpeedKmh = number;
export type SeasonBest = boolean;
export type Cues = Cue[];

/**
 * ``cues.json``: every cue for a match, sorted by ``t_show``.
 */
export interface CueTrack {
  schema_version: SchemaVersion;
  match_id: MatchId;
  languages: Languages;
  cues: Cues;
}
/**
 * One timed overlay instruction.
 */
export interface Cue {
  cue_id: CueId;
  match_id: MatchId1;
  moment_id?: MomentId;
  t_show: TShow;
  duration: Duration;
  layer: Layer;
  template: Template;
  lang?: Lang;
  player_id?: PlayerId;
  team_id?: TeamId;
  priority?: Priority;
  box?: FactBox | null;
  camera?: Camera | null;
  badge?: SpeedBadge | null;
}
/**
 * The text of a box. Casual viewers see headline and body; analysts open the evidence.
 */
export interface FactBox {
  headline: Headline;
  body?: Body;
  evidence?: Evidence;
  analyst?: AnalystDetail | null;
}
/**
 * One checkable fact. ``numbers`` holds the machine values the Verifier compares against.
 */
export interface EvidenceItem {
  id: Id;
  claim_type: ClaimType;
  value: Value;
  source: Source;
  numbers?: Numbers;
}
export interface Numbers {
  [k: string]: number;
}
/**
 * Extra depth shown when the evidence dropdown is opened.
 */
export interface AnalystDetail {
  event_ids?: EventIds;
  pass_map?: PassMap;
  notes?: Notes;
}
export interface Camera {
  shot: CameraShot;
  replay?: Replay;
  replay_speed?: ReplaySpeed;
  highlight?: Highlight;
  trail?: Trail;
  speedo?: Speedo;
  focus?: Focus;
}
export interface SpeedBadge {
  player_id: PlayerId1;
  speed_kmh: SpeedKmh;
  season_best?: SeasonBest;
}
