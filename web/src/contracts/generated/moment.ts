/* Generated from schemas/moment.schema.json by web/scripts/gen-types.mjs. Do not edit. */

export type MomentId = string;
export type MatchId = string;
export type MomentType = "goal" | "corner" | "card" | "big_save" | "big_chance" | "swing";
export type Period = 1 | 2;
export type TStart = number;
export type TPeak = number;
export type TEnd = number;
/**
 * @minItems 2
 * @maxItems 2
 */
export type ReplayWindow = [unknown, unknown];
/**
 * Detector score; above threshold slows the clock
 */
export type Importance = number;
export type ScoringTeam = string | null;
export type PlayerId = string;
export type InvolvementRole =
  "scorer" | "assist" | "build_up" | "shooter" | "keeper" | "defender" | "fouler" | "fouled" | "taker";
export type Events = string[];
/**
 * Touches inside the replay window
 */
export type Touches = number;
export type TopSpeedKmh = number | null;
export type DistanceInWindowM = number | null;
export type Involved = Involvement[];
export type Home = number;
export type Draw = number;
export type Away = number;
/**
 * Change in home win probability; positive favours home
 */
export type Swing = number;
export type ContextRefs = string[];
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
export type Lens = "player" | "club" | "pundit";
/**
 * player_id for the Player lens, team_id for the Club lens
 */
export type SubjectId = string | null;
export type Kind = "box" | "no_box";
export type Headline = string;
export type Body = string;
export type EvidenceIds = string[];
export type Author = "agent" | "template";
/**
 * Agent instance that wrote it
 */
export type Agent = string | null;
export type Status = "approved" | "repaired" | "rejected" | "fallback";
export type Issues = string[];
/**
 * Draft keys to put on screen
 */
export type Show = string[];
/**
 * Camera presets (build plan 3.7).
 */
export type CameraShot = "tv_main" | "spidercam_goal" | "corner_low" | "card_close" | "save_reverse" | "tactical_high";
/**
 * Match time the replay starts
 */
export type ReplayAtT = number | null;
export type MomentStatus = "detected" | "drafted" | "verified" | "scheduled" | "dropped";

/**
 * One detected moment and everything the agents have added to it.
 *
 * Draft keys, used by ``verdicts`` and ``director.show``: ``player:<player_id>``,
 * ``club:<team_id>`` and ``pundit``.
 */
export interface Moment {
  moment_id: MomentId;
  match_id: MatchId;
  type: MomentType;
  period: Period;
  t_start: TStart;
  t_peak: TPeak;
  t_end: TEnd;
  replay_window: ReplayWindow;
  importance: Importance;
  scoring_team?: ScoringTeam;
  involved?: Involved;
  win_prob_before: WinProbability;
  win_prob_after: WinProbability;
  swing: Swing;
  context_refs?: ContextRefs;
  evidence?: Evidence;
  drafts?: Drafts;
  verdicts?: Verdicts;
  director?: DirectorDecision;
  status?: MomentStatus;
}
/**
 * A player who contributed to the moment. Player agents fan out over this list.
 */
export interface Involvement {
  player_id: PlayerId;
  role: InvolvementRole;
  events?: Events;
  touches?: Touches;
  top_speed_kmh?: TopSpeedKmh;
  distance_in_window_m?: DistanceInWindowM;
}
/**
 * Three-way win probability from the home team's point of view. Sums to 1.
 */
export interface WinProbability {
  home: Home;
  draw: Draw;
  away: Away;
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
export interface Drafts {
  player?: Player;
  club?: Club;
  pundit?: Draft | null;
}
export interface Player {
  [k: string]: Draft;
}
/**
 * A lens agent's proposed box, or its decision that the moment gets no box.
 *
 * This interface was referenced by `Player`'s JSON-Schema definition
 * via the `patternProperty` "^[a-z]{3}-\d{2}$".
 *
 * This interface was referenced by `Club`'s JSON-Schema definition
 * via the `patternProperty` "^[a-z]{3}$".
 */
export interface Draft {
  lens: Lens;
  subject_id?: SubjectId;
  kind?: Kind;
  headline?: Headline;
  body?: Body;
  evidence_ids?: EvidenceIds;
  author?: Author;
  agent?: Agent;
}
export interface Club {
  [k: string]: Draft;
}
export interface Verdicts {
  [k: string]: Verdict;
}
/**
 * The Verifier's ruling on one draft. ``final`` is the text to show, if any.
 */
export interface Verdict {
  status: Status;
  issues?: Issues;
  final?: Draft | null;
}
export interface DirectorDecision {
  show?: Show;
  camera?: CameraShot;
  replay_at_t?: ReplayAtT;
  budget_left?: BudgetLeft;
}
/**
 * Boxes left this half, by lens or player track
 */
export interface BudgetLeft {
  [k: string]: number;
}
