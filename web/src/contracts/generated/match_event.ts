/* Generated from schemas/match_event.schema.json by web/scripts/gen-types.mjs. Do not edit. */

export type EventId = string;
export type MatchId = string;
export type T = number;
export type Period = 1 | 2;
export type Clock = string;
export type EventType =
  | "pass"
  | "carry"
  | "shot"
  | "save"
  | "tackle"
  | "interception"
  | "pressure"
  | "foul"
  | "card"
  | "corner"
  | "free_kick"
  | "throw_in"
  | "goal_kick"
  | "goal"
  | "kick_off"
  | "substitution"
  | "offside"
  | "period_start"
  | "period_end";
export type TeamId = string | null;
export type PlayerId = string | null;
export type Start = [unknown, unknown] | null;
export type End = [unknown, unknown] | null;
export type Outcome =
  | "complete"
  | "incomplete"
  | "out"
  | "goal"
  | "saved"
  | "blocked"
  | "off_target"
  | "post"
  | "won"
  | "lost"
  | "caught"
  | "parried"
  | "yellow"
  | "second_yellow"
  | "red";
/**
 * pass: intended receiver
 */
export type ReceiverId = string | null;
export type RelatedPlayerId = string | null;
/**
 * pass, carry, shot
 */
export type DistanceM = number | null;
/**
 * pass: 0 easy to 1 very hard
 */
export type Difficulty = number | null;
/**
 * pass, shot, carry
 */
export type PressureOnPasser = number | null;
/**
 * pass: bypasses a defensive line
 */
export type LineBreaking = boolean | null;
/**
 * pass: ground | lofted | cross | through | long | cut_back
 */
export type PassType = string | null;
/**
 * pass, shot
 */
export type BallSpeedKmh = number | null;
/**
 * shot: expected goals
 */
export type Xg = number | null;
/**
 * shot
 */
export type ShotSpeedKmh = number | null;
/**
 * shot: left_foot | right_foot | head
 */
export type BodyPart = string | null;
/**
 * shot: height at goal line
 */
export type EndHeightM = number | null;
/**
 * carry, pressure
 */
export type DurationS = number | null;
/**
 * carry: peak player speed
 */
export type TopSpeedKmh = number | null;
/**
 * foul, tackle: how reckless
 */
export type Severity = number | null;
/**
 * card, foul: short reason code
 */
export type Reason = string | null;
/**
 * goal
 */
export type AssistPlayerId = string | null;
/**
 * goal
 */
export type OwnGoal = boolean | null;
/**
 * goal: home score after
 */
export type ScoreHome = number | null;
/**
 * goal: away score after
 */
export type ScoreAway = number | null;
/**
 * period_end
 */
export type AddedTimeS = number | null;
export type PossessionId = string | null;

/**
 * One on-ball or match event.
 *
 * Coordinates are in the **attacking frame** of ``team_id`` (see ``matchlens.contracts.pitch``).
 *
 * Conventions:
 * - A scoring shot is a ``shot`` with outcome ``goal``, followed by a ``goal`` event at
 *   the same ``t`` that names the scorer and the score after.
 * - ``related_player_id`` is the other player in a two-player event: the player brought
 *   on (substitution), the player fouled (foul), the ball carrier (tackle, pressure) or
 *   the shooter (save).
 */
export interface MatchEvent {
  event_id: EventId;
  match_id: MatchId;
  t: T;
  period: Period;
  clock: Clock;
  type: EventType;
  team_id?: TeamId;
  player_id?: PlayerId;
  start?: Start;
  end?: End;
  outcome?: Outcome | null;
  receiver_id?: ReceiverId;
  related_player_id?: RelatedPlayerId;
  qualifiers?: Qualifiers;
  possession_id?: PossessionId;
}
/**
 * Optional detail on an event. Fields apply only to the event types noted.
 *
 * Extra keys are allowed here so the simulator can add detail without a schema
 * change; promote a key to a named field once another module depends on it.
 */
export interface Qualifiers {
  distance_m?: DistanceM;
  difficulty?: Difficulty;
  pressure_on_passer?: PressureOnPasser;
  line_breaking?: LineBreaking;
  pass_type?: PassType;
  ball_speed_kmh?: BallSpeedKmh;
  xg?: Xg;
  shot_speed_kmh?: ShotSpeedKmh;
  body_part?: BodyPart;
  end_height_m?: EndHeightM;
  duration_s?: DurationS;
  top_speed_kmh?: TopSpeedKmh;
  severity?: Severity;
  reason?: Reason;
  assist_player_id?: AssistPlayerId;
  own_goal?: OwnGoal;
  score_home?: ScoreHome;
  score_away?: ScoreAway;
  added_time_s?: AddedTimeS;
  [k: string]: unknown;
}
