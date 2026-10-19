import { useMemo, useState } from "react";
import type { Match, PlayerInfo } from "../model/match";
import { LENSES, type Lens, type Viewer } from "../model/viewer";
import { LANGUAGE_NAMES } from "./i18n";

interface Props {
  match: Match;
  viewer: Viewer;
  setViewer: (v: Viewer) => void;
}

const LENS_ICONS: Record<Lens, React.ReactNode> = {
  player: (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="7.5" r="3.5" fill="currentColor" />
      <path d="M5 20c.8-4.2 3.5-6.5 7-6.5s6.2 2.3 7 6.5z" fill="currentColor" />
    </svg>
  ),
  club: (
    <svg viewBox="0 0 24 24">
      <path d="M12 2.5 4 5.5v6c0 5 3.4 8.7 8 10 4.6-1.3 8-5 8-10v-6z" fill="currentColor" />
    </svg>
  ),
  pundit: (
    <svg viewBox="0 0 24 24">
      <path d="M4 18 9 11l4 4 7-9" stroke="currentColor" strokeWidth="2.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="20" cy="6" r="2" fill="currentColor" />
    </svg>
  ),
};

export function LensPanel({ match, viewer, setViewer }: Props) {
  return (
    <div className="panel">
      <h2 className="panel-title">Lens</h2>
      <div className="lens-list" role="radiogroup" aria-label="Lens">
        {LENSES.map((l, i) => (
          <button
            key={l.id}
            role="radio"
            aria-checked={viewer.lens === l.id}
            className={`lens-btn lens-${l.id}${viewer.lens === l.id ? " is-on" : ""}`}
            style={l.id === "club" ? { ["--accent" as string]: match.clubs.get(viewer.teamId)?.colours.primary } : undefined}
            onClick={() => setViewer({ ...viewer, lens: l.id })}
          >
            <span className="lens-icon">{LENS_ICONS[l.id]}</span>
            <span className="lens-text">
              <b>{l.label}</b>
              <small>{l.blurb}</small>
            </span>
            <kbd>{i + 1}</kbd>
          </button>
        ))}
      </div>

      {viewer.lens === "player" && <PlayerPicker match={match} viewer={viewer} setViewer={setViewer} />}
      {viewer.lens === "club" && <ClubPicker match={match} viewer={viewer} setViewer={setViewer} />}
      {viewer.lens === "pundit" && (
        <p className="panel-note">
          The Pundit calls out brilliance from anyone: line-breaking passes, presses that win the ball, and swings in
          momentum. In replays it draws the ball's path.
        </p>
      )}

      <h2 className="panel-title">Language</h2>
      <div className="seg">
        {match.cueTrack.languages.map((l) => (
          <button key={l} className={viewer.lang === l ? "is-on" : ""} onClick={() => setViewer({ ...viewer, lang: l })}>
            {LANGUAGE_NAMES[l] ?? l}
          </button>
        ))}
      </div>
    </div>
  );
}

function PlayerPicker({ match, viewer, setViewer }: Props) {
  const [q, setQ] = useState("");
  // Players with something to show in this match: worth surfacing in the picker.
  const featured = useMemo(() => {
    const s = new Map<string, number>();
    for (const c of match.cueTrack.cues) if (c.layer === "player" && c.player_id && c.template === "fact_box") s.set(c.player_id, (s.get(c.player_id) ?? 0) + 1);
    return s;
  }, [match]);
  const needle = q.trim().toLowerCase();
  const filter = (p: PlayerInfo) => !needle || p.name.toLowerCase().includes(needle) || String(p.shirt) === needle;

  return (
    <div className="picker">
      <h2 className="panel-title">Favourite player</h2>
      <input className="search" placeholder="Search name or number" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="picker-scroll">
        {[match.home, match.away].map((club) => {
          const list = match.lineup(club.team_id).filter(filter);
          if (!list.length) return null;
          return (
            <div key={club.team_id} className="picker-team">
              <div className="picker-team-name">
                <span className="crest" style={{ background: club.colours.primary }} />
                {club.name}
              </div>
              {list.map((p) => (
                <button
                  key={p.player_id}
                  className={`prow${viewer.playerId === p.player_id ? " is-on" : ""}`}
                  onClick={() => setViewer({ ...viewer, playerId: p.player_id })}
                >
                  <span
                    className="prow-num"
                    style={{ background: club.colours.primary, color: club.colours.text, borderColor: club.colours.secondary }}
                  >
                    {p.shirt}
                  </span>
                  <span className="prow-name">{p.name}</span>
                  <span className="prow-slot">{p.slot}</span>
                  {featured.has(p.player_id) && (
                    <span className="prow-star" title={`${featured.get(p.player_id)} moment${featured.get(p.player_id)! > 1 ? "s" : ""} in this match`}>
                      ●
                    </span>
                  )}
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ClubPicker({ match, viewer, setViewer }: Props) {
  return (
    <div className="picker">
      <h2 className="panel-title">Favourite club</h2>
      <div className="club-list">
        {[match.home, match.away].map((c) => (
          <button
            key={c.team_id}
            className={`club-card${viewer.teamId === c.team_id ? " is-on" : ""}`}
            style={{ ["--club" as string]: c.colours.primary, ["--club-2" as string]: c.colours.secondary }}
            onClick={() => setViewer({ ...viewer, teamId: c.team_id })}
          >
            <span className="club-badge">{c.team_id.toUpperCase()}</span>
            <span className="club-name">
              <b>{c.name}</b>
              <small>{c.stadium}</small>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
