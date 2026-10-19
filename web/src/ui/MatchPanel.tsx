import { useSyncExternalStore } from "react";
import type { Match } from "../model/match";
import { railItems } from "../model/cues";
import type { Viewer } from "../model/viewer";
import type { Engine } from "../player/engine";

/** Right sidebar: match context, key moments to jump to, and the lens's events rail. */
export function MatchPanel({ match, engine, viewer }: { match: Match; engine: Engine; viewer: Viewer }) {
  // Only re-render when the whole second changes, not every frame.
  const second = useSyncExternalStore(engine.subscribe, () => Math.floor(engine.getSnapshot().t));
  const wp = match.meta.pre_match_win_prob;
  const rail = railItems(match.cues(viewer.lang), viewer).filter((c) => c.t_show <= second);
  const { home, away } = match;

  return (
    <div className="panel">
      <h2 className="panel-title">Match</h2>
      <div className="match-card">
        <div className="mc-line">
          {match.meta.stadium} · {match.meta.weather.condition}, {match.meta.weather.temperature_c}°C
        </div>
        {match.meta.stakes?.notes?.map((n) => (
          <div key={n} className="mc-stake">
            {n}
          </div>
        ))}
        <div className="wp">
          <div className="wp-label">Pre-match win probability</div>
          <div className="wp-bar">
            <span style={{ width: `${wp.home * 100}%`, background: home.colours.primary }} />
            <span style={{ width: `${wp.draw * 100}%` }} className="wp-draw" />
            <span style={{ width: `${wp.away * 100}%`, background: away.colours.primary }} />
          </div>
          <div className="wp-nums">
            <span>
              {home.team_id.toUpperCase()} {Math.round(wp.home * 100)}%
            </span>
            <span>Draw {Math.round(wp.draw * 100)}%</span>
            <span>
              {away.team_id.toUpperCase()} {Math.round(wp.away * 100)}%
            </span>
          </div>
        </div>
      </div>

      <h2 className="panel-title">Key moments</h2>
      <div className="moments">
        {match.markers.map((m) => (
          <button
            key={`${m.kind}${m.t}`}
            className={`moment moment-${m.kind}${second >= m.t ? " is-past" : ""}`}
            onClick={() => engine.seek(m.t - 4)}
          >
            <span className="moment-clock">{match.clock(m.t)}</span>
            <span className="moment-dot" style={{ background: match.clubs.get(m.teamId)?.colours.primary }} />
            <span className="moment-label">{m.label}</span>
          </button>
        ))}
      </div>

      {rail.length > 0 && (
        <>
          <h2 className="panel-title">Timeline</h2>
          <div className="rail">
            {rail.map((c) => (
              <div key={c.cue_id} className="rail-item">
                <span className="moment-clock">{match.clock(c.t_show)}</span>
                <div>
                  <b>{c.box?.headline}</b>
                  {c.box?.body && <p>{c.box.body}</p>}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      <p className="panel-foot">
        Space play/pause · ← → seek · N next moment · 1–3 lens · F full screen · M mute
      </p>
    </div>
  );
}
