import type { Cue } from "../contracts";

export type Lens = "player" | "club" | "pundit";

export const LENSES: { id: Lens; label: string; blurb: string }[] = [
  { id: "player", label: "Player", blurb: "Follow one player through every moment" },
  { id: "club", label: "Club", blurb: "What each moment means for your club" },
  { id: "pundit", label: "Pundit", blurb: "Tactics and brilliance, from anyone" },
];

/** Everything that personalises the stream. All of it is applied in the browser. */
export interface Viewer {
  lens: Lens;
  playerId: string;
  teamId: string;
  lang: string;
}

/** Does this cue belong on this viewer's screen? */
export function matchesViewer(cue: Cue, v: Viewer): boolean {
  switch (cue.layer) {
    case "global":
      return true;
    case "player":
      return v.lens === "player" && cue.player_id === v.playerId;
    case "club":
      return v.lens === "club" && cue.team_id === v.teamId;
    case "pundit":
      return v.lens === "pundit";
  }
}
