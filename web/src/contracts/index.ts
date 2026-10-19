// The player reads match data only through these types, generated from schemas/.
export type { CueTrack, Cue, FactBox, EvidenceItem, Camera, CameraShot, Layer } from "./generated/cue_track";
export type { Frame } from "./generated/frame";
export type { League, Club, Player } from "./generated/league";
export type { MatchMeta, TeamSheet } from "./generated/match_meta";
export type { MatchEvent } from "./generated/match_event";

/** Contract constants mirrored from matchlens/contracts/common.py. */
export const PITCH_LENGTH_M = 105;
export const PITCH_WIDTH_M = 68;
export const FRAME_HZ = 10;
