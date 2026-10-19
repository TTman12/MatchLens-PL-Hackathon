/* Generated from schemas/frame.schema.json by web/scripts/gen-types.mjs. Do not edit. */

export type T = number;
/**
 * @minItems 3
 * @maxItems 3
 */
export type Ball = [unknown, unknown, unknown];

/**
 * One tracking frame, in the **pitch frame** (see ``matchlens.contracts.pitch``).
 *
 * Stored and streamed as JSON Lines, one frame per line, in ``t`` order. Players who are
 * not on the pitch (bench, sent off, substituted) are absent from ``players``.
 */
export interface Frame {
  t: T;
  ball: Ball;
  players: Players;
}
export interface Players {
  /**
   * @minItems 4
   * @maxItems 4
   *
   * This interface was referenced by `Players`'s JSON-Schema definition
   * via the `patternProperty` "^[a-z]{3}-\d{2}$".
   */
  [k: string]: [unknown, unknown, unknown, unknown];
}
