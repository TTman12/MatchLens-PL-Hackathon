# Football stats for tactical inference, without tracking

Research for the 20 Oct 2026 pivot: away from the match simulator, toward a system that reads team-level stats over any window and shows, as graphics and numbers rather than text, what is happening tactically (control, territory, tempo, pressure, momentum, playstyle) during quiet spells.

Labels: **[Sourced]** is backed by a linked source. **[Known]** is standard analytics practice from my own knowledge, not re-checked today. **[Inferred]** is my design reasoning. Typical numbers marked "≈" are ballpark Premier League values from memory; treat them as calibration starting points, not facts to put on screen.

This does not repeat `landscape-and-ideas.md` (who ships what) or `fan-emotions-and-amplifiers.md` (why fans care).

---

## 0. The short version

**The core insight:** event data alone (who did what, where, when, with what outcome) is enough to read almost every team-level tactical concept that commentators talk about. Tracking adds shape and compactness, but you can proxy most of it from *where* events happen. And the most interesting signal is rarely the raw number, it is **the number against that team's own normal, given the score**. "62% possession" is wallpaper; "62%, which is 15 points above their usual, while losing" is a story.

**The twelve metrics that carry most of the load** (all computable from team-level event aggregates over a rolling window):

| # | Metric | What it reads | Formula (event-only) |
|---|---|---|---|
| 1 | **Possession share** (by time or by passes) | Who has the ball | team passes ÷ both teams' passes in window |
| 2 | **Field tilt** | Who has the *territory* | team final-third passes ÷ both teams' final-third passes [Sourced] |
| 3 | **Pass completion, split by third** | Safe circulation vs risky progression | completed ÷ attempted, per third |
| 4 | **Passes per minute of possession** | Tempo of circulation | team passes ÷ team possession minutes |
| 5 | **Direct speed** (m/s upfield) | Patient vs vertical | metres gained toward goal ÷ sequence duration [Sourced: Opta, PL range 1.4 to 2.1 m/s] |
| 6 | **Passes per sequence** | Build-up vs bypass | mean passes in each open-play sequence |
| 7 | **PPDA** | Pressing intensity | opponent passes in their own 60% ÷ our defensive actions there [Sourced] |
| 8 | **Defensive action height** | Where the block sits | mean x of our tackles, interceptions, pressures, fouls |
| 9 | **High turnovers** | Is the press *working* | our sequences starting in open play within 40 m of their goal [Sourced: Opta] |
| 10 | **Threat / possession value per minute** (xT or similar) | Danger, not just volume | sum of value added by each action |
| 11 | **Box entries and xG** | End product | passes/carries into the box; sum of shot xG |
| 12 | **Turnover rate and possession-change rate** | Control vs chaos | possession changes per minute, ball-losses per sequence |

Combine these and the deductions fall out. Tristan's own example works directly: **15 passes in a minute, 95% completion, almost all in their own half** reads as high possession, high completion, high tempo-of-circulation, *low* field tilt, *low* direct speed, *zero* box entries. That pattern is "**controlling, not attacking**" (often called sterile or patient possession). If the opponent's PPDA is also high (they're not pressing) the second half of the story is "**and the opponent is happy to let them**", which is a mid or low block.

---

## 1. What football data exists

### 1.1 The four layers

| Layer | What it is | Who makes it | Useful to us? |
|---|---|---|---|
| **Match facts** | Score, cards, subs, lineups, formations, possession %, shots, corners. The "box score". | Every broadcaster, free sites | Yes, but too coarse to explain anything alone |
| **Event data** | One row per on-ball action with x/y, time, team, player, type, outcome and qualifiers. ≈1,500 to 2,000 events per match. | Opta (Stats Perform), StatsBomb (Hudl), Wyscout (Hudl) | **This is our layer.** Everything below is derived from it. |
| **Tracking data** | x/y of all 22 players and ball at 10 to 25 Hz. ≈3 million points per match. | Second Spectrum / Genius, SkillCorner (from broadcast video), Hawk-Eye | Out of scope by Tristan's choice. Section 4 lists what we lose. |
| **Derived models** | xG, xA, xT, possession value (OBV, VAEP, Opta PV), win probability, phases of play, playing styles | Providers and the public analytics community | Yes. All computable from event data. |

### 1.2 How event data is structured [Known, cross-checked against StatsBomb and socceraction docs, Sourced]

A provider event row has the same core fields everywhere; only names differ:

- **When:** period, minute, second (StatsBomb also has a `duration`).
- **Who:** team, player, and for passes the recipient.
- **What:** event type (pass, carry, dribble, shot, duel, tackle, interception, clearance, block, ball recovery, pressure, foul, card, set piece, sub, offside...).
- **Where:** start x/y and, for passes, carries and shots, end x/y. Usually a normalised pitch (Opta 0 to 100 both axes, StatsBomb 120 × 80 yards) with each team always attacking left to right.
- **Outcome:** complete/incomplete, won/lost, on target/off target/goal.
- **Qualifiers:** body part, pass height, cross, through ball, switch, long ball, set-piece type, `under_pressure`, `counterpress` (a pressing action within 5 seconds of losing the ball) [Sourced: socceraction schema].
- **Grouping keys:** a possession id (StatsBomb) or an implicit sequence (Opta). Opta's model chains events into **sequences** (unbroken passages by one team, ending when the opponent touches it or play stops) and sequences into **possessions** [Sourced: Stats Perform].

Our repo's `match_event.schema.json` already matches this shape (pitch metres 105 × 68, `possession_id`, qualifiers for distance, difficulty, pressure, line-breaking, ball speed). **We do not need a new schema for events**; we need a new layer on top.

### 1.3 Open reference datasets [Known]

| Dataset | Content | Licence note |
|---|---|---|
| StatsBomb open data (GitHub) | Full event data for several thousand matches (some competitions in full), with 360 freeze-frames for a few tournaments | Free under a user agreement that asks for attribution. **Not** for redistribution as our data; fine for studying distributions privately. |
| Wyscout public dataset (Pappalardo et al., 2019, *Scientific Data*) | Every event for a full season of 7 competitions (incl. PL 2017-18) | CC BY 4.0. Safest to calibrate against, with attribution. |
| Metrica Sports sample data | 3 anonymised matches of tracking + events | Open, for reference |
| SkillCorner open data | Broadcast-derived tracking for a few matches | Open, for reference |

The rules say we must use synthetic data and that no real PL data is redistributed. **Recommendation [Inferred]:** never ship any real rows. If we use anything, use published league-level rates (from Opta Analyst articles or the CC BY Wyscout set) only as calibration targets for the generator, and say so in the README.

### 1.4 What providers already turn into graphics [Sourced]

- **Opta Match Momentum** (shown on Flashscore and others): every in-possession action is valued by how much it raises or lowers the chance of scoring; values are summed per minute and the bar shows which team had more. It does not depend on shots alone.
- **Bundesliga Match Facts (AWS):** a 0 to 10 threat value per team, displayed as the difference, reset each half, built from shots (with xG), attacking-zone entries, crosses and box receptions. Also **Attacking Zones** (final third split into four vertical lanes, share of entries per lane), Most Pressed Player, Ball Recovery Time, Passing Profile, Average Positions, Speed Alert, Win Probability.
- **Opta playing styles:** eight team styles incl. Build Up (open-play sequences of 10+ passes ending in a shot or box touch), Direct Attack, Counter Attack, High Press (controlled pressing regains, excluding counter-press, and only after the opponent has held the ball for a set time), with direct speed in m/s.
- **FIFA Enhanced Football Intelligence:** phases of play. In possession: build-up (opposed/unopposed), progression, final third, counter-attack, etc. Out of possession: high press, high block (high but not pressing), mid block, low block, counter-press, recovery. These are exactly the "states" we want to deduce, though FIFA derives them from tracking.

**The gap for us [Inferred]:** everyone shows the *metric*. Momentum bars show *who* is on top, not *how* (pressing? siege? counter-attacks?). Nobody publicly shows "the tactical state right now, and how it changed" as a graphic.

---

## 2. Pitch zones: the vocabulary of "where"

Every "where" stat needs a zone scheme. Use a few, all derived from start/end x/y [Known]:

- **Thirds** along the length: defensive (0 to 35 m), middle (35 to 70 m), final (70 to 105 m). Opta's "high turnover" uses "within 40 m of goal" instead.
- **Halves** (own / opposition).
- **Five vertical lanes:** left wing, left half-space, centre, right half-space, right wing (lanes of ≈13.6 m on a 68 m pitch). Bundesliga uses four lanes for its Attacking Zones.
- **18-zone grid** (6 lengthwise × 3 across) for heatmaps; **12 × 8** (or 16 × 12) grid for xT.
- **Special zones:** penalty box, "Zone 14" (central area just outside the box), and the "golden zone" (central area between the posts, inside the box).

The 6 × 3 grid is the right resolution for an on-screen territory graphic: readable at a glance, enough to show "all down the left".

---

## 3. Metric catalogue, by what it explains

Each entry: **metric → formula from team-level events → what it tells you → pitfall.** Window means the rolling window we'd compute it over (section 5.1).

### 3.1 Control (who is dictating)

- **Possession share.** Pass-count share is the industry norm (Opta's possession % is pass-based); time-based is more intuitive on screen. Tells who has the ball. *Pitfall:* possession ≠ control. Teams that lead often give the ball away on purpose (score effects, 5.2).
- **Pass completion %, overall and by third.** High completion in own third is cheap; completion in the final third is the hard part. *The gap between own-half and final-third completion* is a strong signal of a block that's working.
- **Passes per sequence / longest sequences.** Long chains = control through circulation.
- **Ball-retention after regain:** share of our sequences that survive 3+ passes. Low = chaotic, can't keep it.
- **Turnovers per minute** (both teams combined) and **possession changes per minute.** Low = one team in control; high = **chaos**. A clean "control vs chaos" axis that the challenge brief names explicitly.

### 3.2 Territory (where the game is being played)

- **Field tilt** = our final-third passes ÷ both teams' final-third passes [Sourced]. Better than possession for "who's on top": a team can have 40% of the ball and 60% field tilt.
- **Average x of all our touches** (team "centre of gravity"). One number for "how high is the team playing".
- **Final-third entries and box entries** (pass or carry that crosses into the zone). Counts and per minute.
- **Opponent's sequence end-points:** where their passages die tells you where we stop them, a proxy for our press/block height [Sourced: Opta].
- **Zone heatmap** (6 × 3) of our touches vs theirs. The best single graphic for territory.

### 3.3 Tempo and rhythm

- **Passes per minute of possession.** Circulation speed. ≈ 15 to 20 for top possession sides [≈].
- **Direct speed (m/s upfield in a sequence)** [Sourced: PL 2024-25 range ≈1.4 (Man City) to ≈2.1 (Forest)]. The cleanest "patient vs direct" dial.
- **Sequence duration** and **time to first forward pass** after regaining.
- **Progressive passes / carries per minute** (moves the ball ≥10 m closer to goal, or into the box). Tempo with intent, not just ball-shuffling.
- **Long-ball share** (passes > 30 to 32 m) and **switches of play.** Direct vs build-up.
- **Ball-in-play rhythm:** time between stoppages, number of stoppages (fouls, throw-ins, goal kicks) per 5 minutes. A rising stoppage count is "the game has gone bitty", often deliberate when a team is protecting a lead.
- **Rhythm/volatility:** rolling standard deviation of the momentum or threat series. Low variance = one-way traffic or a dead game; high variance = end-to-end.

### 3.4 Pressure and pressing (out of possession)

- **PPDA** (passes per defensive action): opponent passes in their defensive 60% ÷ our defensive actions (tackles, interceptions, fouls, challenges) in that zone. Lower = more aggressive press. Introduced by Colin Trainor (2014); definitions vary by provider [Sourced]. ≈ 8 (heavy press) to 16+ (sit off) [≈]. *Pitfall:* territory confounds it; a dominant team defends higher simply because the ball is there. Report it alongside field tilt.
- **Defensive action height:** mean x of our defensive actions. ≈ the line where we engage. One number, great on a pitch graphic as a horizontal line.
- **High turnovers:** our open-play sequences starting within 40 m of their goal [Sourced]. **The "is the press paying off" number.** And the follow-up: % of high turnovers ending in a shot (City 2024-25: 300 high turnovers, 13.7% ending in a shot [Sourced]).
- **Counter-press regains:** regains within 5 seconds of losing the ball. Tells you whether a team is trying to win it back immediately.
- **Pressures and `under_pressure` share** (if the data has pressure events, as StatsBomb and our schema do): share of the opponent's passes made under pressure, and their completion under pressure vs not. "Press is forcing errors" = their completion under pressure drops.
- **Opponent's long-ball share rising** is a classic sign the press is working: they can't play through, so they go long.
- **Goal-kick behaviour:** share of their goal kicks played short vs long. Short-to-long shift = they've given up building out against the press.
- **Ball recovery time:** average seconds from losing the ball to regaining it (Bundesliga stat) [Sourced]. Lower = more intense out-of-possession.

### 3.5 Threat and danger (is the control producing anything?)

- **xG** per shot and cumulative; **non-penalty xG**; **xG per shot** (quality vs volume).
- **Expected threat (xT)** [Known: Karun Singh; grid value = probability that possession from that cell ends in a goal within the next few actions]. Every completed pass/carry earns xT(end) − xT(start). Sum per minute = **threat per minute**. Credits dangerous build-up that doesn't end in a shot. Easy to compute: a static grid lookup.
- **Possession value models** (VAEP, StatsBomb OBV, Opta PV): richer than xT (values every action incl. defensive ones) but need a trained model. For synthetic data, xT is enough and transparent.
- **Box entries, touches in box, crosses, cutbacks, Zone 14 entries.**
- **Shots per final-third entry** (conversion of territory into chances). Siege with no shots = the block is holding.

### 3.6 Momentum

Every momentum stat on the market is a smoothed, differenced threat measure [Sourced: Opta, Bundesliga]. Our repo already has one (`swing/stats/momentum.py`: threat points over 5 minutes, `(home − away)/(home + away)`). Improvements [Inferred]:
- Use xT-per-action as the threat input, so build-up counts proportionally.
- Exponential decay instead of a hard 5-minute box (a half-life of ≈2 to 3 minutes avoids the cliff when an event leaves the window).
- Track the **derivative** (who is gaining) as well as the level. "Momentum shifting" is the graphic moment, not "momentum is high".

### 3.7 Width and channels (where they attack)

- **Lane shares of final-third entries** (left / half-spaces / centre / right). Bundesliga's Attacking Zones [Sourced].
- **Crosses per final-third entry.** High = wide, crossing team; low = combination through the middle.
- **Switches of play per minute.** Trying to move a block side to side.
- **Mismatch spotting [Inferred]:** combine our lane share with the opponent's defensive-action lane share. "60% of their attacks down our right, and our right side has made the fewest defensive actions" is a story a commentator loves, and it is pure event aggregation.

### 3.8 Transitions

- **Counter-attacks:** sequences starting in own half after a regain, reaching the final third (or a shot) within ≈10 to 15 s with few passes (Opta-style) [Known].
- **Passes per transition sequence** (defensive third to final third): Burnley 3.9 vs Liverpool 7.7 in 2024-25 [Sourced]. Direct vs patient transition.
- **Shots conceded within 15 s of losing the ball:** vulnerability in transition.

### 3.9 Discipline, fatigue and game management

- **Fouls per minute, especially in the middle third after losing the ball** = tactical fouling (stopping counters).
- **Time-wasting proxies:** goal-kick and throw-in durations rising (we have timestamps of the stoppage and the restart), subs late in the game when leading.
- **Fatigue proxies [Inferred, weak]:** falling pressing intensity (PPDA rising, defensive action height dropping) and falling pass completion in the last 20 minutes. Without tracking we can't see distance or sprints, so phrase it as "pressing has dropped off", not "they're tired".

### 3.10 Set pieces

- Corners, free kicks in the final third, long throws; share of xG from set pieces. "They've had 6 corners in 10 minutes" is a pressure story on its own.

---

## 4. What we lose without tracking, and the event-only proxy

| Concept | Needs tracking for... | Event-only proxy | Confidence |
|---|---|---|---|
| Defensive line height | Exact position of the back line | Mean x of defensive actions; opponents' sequence end-points; offsides won | Medium |
| Compactness / block shape | Distances between lines | Opponent's completion into Zone 14 and between-lines receptions (if receptions are logged); "line-breaking" pass share (our schema already has `line_breaking`) | Low-medium |
| Pressing intensity | Distance/speed of nearest defenders | PPDA, pressure events, `under_pressure` share, ball recovery time | Medium-high |
| Formation | Average positions | Not reliably. Use match metadata (declared formation) and say so. | Low |
| Off-ball runs, overloads | Everyone's position | Not available. Lane shares hint at overloads. | Low |
| Physical output (distance, sprints, speed) | Tracking | Not available. Only ball speed and shot speed from event qualifiers. | None |

**Takeaway [Inferred]:** event aggregates cover control, territory, tempo, pressing, threat, momentum, width, transitions and game management well. They cover shape and physical output poorly. Our product should stick to the first group and be honest about it.

---

## 5. Turning numbers into tactical meaning

### 5.1 Windows

Use several at once [Inferred]:
- **Last 2 minutes**: noisy but responsive; good for "right now" flashes (≈15 to 25 passes per team-minute of possession means 2 minutes is enough for completion and pass-location shares).
- **Last 5 and 10 minutes**: the main "phase" window. Most rules run here.
- **Half / match to date**: baseline for "this is different from earlier".
- **Team's own season profile**: baseline for "this is different from how they normally play".

Ratios need minimum counts (e.g. no completion % from fewer than 8 passes) or a Bayesian shrink toward the team's baseline, otherwise a 3-from-3 minute reads as "100% accuracy".

### 5.2 Context that changes what a number means [Known]

- **Score effects (game state):** leading teams typically cede possession and territory and defend deeper; trailing teams push. A team 1-0 up with 35% possession is often *in control*. Every rule must condition on score and minute.
- **Red cards:** 10 v 11 changes every baseline.
- **Home/away and pre-match strength:** a favourite having 60% is normal; an underdog having 60% is news.
- **Own baseline:** z-score each metric against the team's season profile (and against league average). The overlay should show *deviation* as much as level.

### 5.3 A feature vector per team per window

Normalise each metric to a 0 to 1 or z-score, so rules and agents compare like with like. Minimal set (≈20 numbers per team):

`possession, field_tilt, completion_own_half, completion_final_third, passes_per_poss_min, direct_speed, passes_per_sequence, long_ball_share, progressive_per_min, final_third_entries, box_entries, xg, xt_per_min, ppda, def_action_height, high_turnovers, counterpress_regains, opp_completion_under_pressure, turnovers_per_min, fouls_per_min, lane_share[5], set_pieces`

Plus context: `score_diff, minute, men_on_pitch, pre_match_win_prob, baseline_z[...]`.

### 5.4 Tactical states: a rule library [Inferred, grounded in sections 3 and 1.4]

Each state is a named pattern with conditions, a confidence, the metrics that triggered it (the evidence), and the graphic it drives. Illustrative, for team A vs team B over the last 5 to 10 minutes:

| State | Conditions (sketch) | Graphic |
|---|---|---|
| **Sterile control** ("controlling, not attacking") | possession ≥ 60%, completion ≥ 88%, field tilt ≤ 50%, box entries ≤ 1, direct speed low | Control meter far to A; territory heatmap showing A's touches in own half; a "box entries: 0" counter |
| **Siege** | field tilt ≥ 70%, final-third entries high, B's def action height low, A's xG/shot low | Territory bar at 75/25; B's block line drawn deep; shots counter with small xG |
| **Press is winning** | A's PPDA ≤ 8, A's def action height high, A's high turnovers ≥ 2, B's long-ball share up vs baseline, B's completion under pressure down | Press line high up the pitch; high-turnover dots in B's half; B's pass-accuracy dial dropping |
| **Press is being beaten** | A's PPDA low but B's direct speed high and B's progressive passes up; B's counter-attacks ≥ 1 | Press line high with arrows through it |
| **Low block holding** | B possession ≤ 35%, B def action height low, A's final-third completion < own-half completion by 15+ points, A's shots per entry low | Two-number comparison: A's completion in own half vs final third |
| **Counter-attack threat** | B possession low but B direct speed high, B shots from transitions, A turnovers in middle third | Transition arrows; "seconds from regain to shot" |
| **End-to-end / chaos** | possession changes/min high, completion low both sides, both xT rising, momentum volatility high | Control meter swinging; chaos gauge |
| **Game management** | A leading late, A possession low by choice, stoppage count up, fouls up, A's long-ball share up | Clock + stoppage counter; "ball in play: 31 s of the last 2 min" |
| **Probing one flank** | A's lane share on one side ≥ 45%, crosses up | Lane arrows on the pitch |
| **Overload vs weak side** | A's lane share high on a side where B makes few defensive actions | Highlighted lane with both numbers |
| **Shift / turn of the tide** | change-point in momentum or field tilt (5.5) | Before/after split bar ("last 10 min vs previous 10") |
| **Dead spell** | low entries both sides, low xT, slow tempo | Good moment for a season-context graphic instead |

States are not exclusive: A can be "sterile control" while B is "low block holding". The pair is the story.

### 5.5 Detecting change, not just state

The overlays should fire on **transitions between states** and on **unusual deviations**, not every minute [Inferred]:
- **Change-point detection** on the main series (momentum, field tilt, PPDA, tempo): CUSUM or a simple two-window comparison (last 5 min vs previous 10 min, with a threshold in z-score units).
- **Deviation alarm:** a metric is > 2 SD from the team's own baseline given game state.
- **Persistence:** a state must hold for ≥ 2 to 3 minutes before it's announced, and the editor enforces a cooldown (the existing Director attention budget already does this).
- **Trigger on quiet:** the brief says these are for quiet moments. The quiet detector is itself a rule: no shot, corner, card or box entry for N seconds, and low xT per minute.

### 5.6 Where the agents fit [Inferred]

A deterministic core with agents on top, which keeps every number honest and still shows real agentic design:

1. **Aggregator (code, not an LLM):** rolls events into the feature vectors per window, every few seconds. Pure, testable, fast.
2. **Pattern matcher (code):** runs the rule library and change detectors; outputs candidate states with confidence and evidence (the metric values and the event ids behind them).
3. **Tactical analyst agent (LLM):** gets the candidates, the feature vectors and context, and does what rules do badly: resolves conflicts between candidates, picks the one that is interesting *now*, notices combinations the rules don't name, and chooses which numbers to show. It can call tools (`get_window(team, from, to)`, `compare_windows`, `team_baseline`, `zone_breakdown`) via the existing Match-State MCP server, so it can drill in ("is the press working? check B's long-ball share last 5 vs first 20 min").
4. **Graphics director agent:** maps the chosen state to a graphic template and its numbers (no prose), respecting the attention budget and the quiet-moment trigger.
5. **Verifier (code + LLM):** every number on a graphic must be recomputable from the aggregates; anything else is dropped. Same rule as today.
6. **Optional commentator-notes agent:** a one-line talking point per graphic for the commentator's screen, not the viewer's, which satisfies "narratives" and "multi-language" without putting text on the broadcast.

A pure rules system would work for the demo; the agent layer earns its place on conflict resolution, novelty and drill-down. A pure LLM system would hallucinate numbers. The hybrid is the defensible design.

---

## 6. Synthesising realistic data without a match simulator

We do not need a physics or movement simulator to feed this system. Three options, cheapest first [Inferred]:

1. **Script-driven possession-chain generator (recommended).**
   - A **tactical script** per team over time (latent state per minute: e.g. "press high 0-20", "sit deep after leading 60+", "chasing 80+"), chosen from storylines.
   - A **Markov chain over pitch zones** for each possession: from the current zone, pick the next action (short pass, long pass, carry, cross, shot, loss) with probabilities set by the team's style parameters *and* the current tactical state of both teams (a high press raises loss probability in the build-up zones, etc.).
   - Each action gets a duration, so tempo and direct speed emerge naturally.
   - Output: the same event rows our schema already defines, but **no player positions or frames**. Players are still named on events for flavour.
   - **The big win:** the generator knows the true tactical state at every minute, so we get **ground truth to evaluate the deducer against** ("the system called 'press is winning' in 83% of minutes where the script said the press was on"). That is a strong technical-implementation and evals story for the judges.
2. **Direct aggregate generator.** Skip events; generate per-minute team stats from the script with noise. Fast and controllable, but shallower: no event ids to cite, no zone heatmaps from first principles. Fine for a fallback.
3. **Keep the existing simulator as the event source.** It already produces events. But Tristan's point stands: it is the part that keeps breaking, and movement realism no longer matters if nothing is drawn on a pitch.

**Calibration targets** (≈ PL per team per match, to tune option 1) [≈ from memory unless marked]:

| Stat | Typical | Range across teams |
|---|---|---|
| Passes attempted | ≈ 450 to 480 | ≈ 300 (direct) to 700+ (possession) |
| Pass completion | ≈ 80 to 83% | ≈ 70% to 90% |
| Shots | ≈ 12 to 13 | ≈ 8 to 18 |
| xG | ≈ 1.4 to 1.5 | ≈ 0.8 to 2.3 |
| PPDA | ≈ 11 to 12 | ≈ 8 to 16+ |
| Direct speed | | 1.4 to 2.1 m/s [Sourced] |
| High turnovers | ≈ 6 to 8 | City ≈ 8 per match (300 over a season) [Sourced] |
| Passes per transition sequence | | 3.9 to 7.7 [Sourced] |
| Ball in play | ≈ 55 to 60 min | |
| Corners | ≈ 5 | ≈ 3 to 7 |

Calibrate style *contrasts* as much as means: the generator must make a Forest-like direct team and a City-like possession team look clearly different on the dials, or the graphics have nothing to show.

---

## 7. Graphics that carry this without text

Tristan wants graphics and numbers, not sentences. Candidates that map one-to-one to the metrics above [Inferred]:

- **Control meter:** a horizontal bar with one club at each end, the needle driven by a blend of possession, field tilt and xT share. Moves smoothly, with a ghost marker for the team's normal.
- **Territory pitch:** the 6 × 3 zone heatmap, split by team colour.
- **Press line:** a pitch with a horizontal line at the team's defensive action height, plus PPDA as a big number and high-turnover dots.
- **Tempo dial:** passes per minute and direct speed as a speedometer pair, with the team's season average marked.
- **Attack lanes:** five arrows into the final third, thickness = share of entries.
- **Before/after split:** "last 10 min vs previous 10" for any two metrics when a shift is detected.
- **Accuracy by zone:** pass completion in own half vs final third, side by side. The "they can't break the block down" graphic.
- **Chaos gauge:** possession changes per minute.
- **Momentum ribbon:** the existing momentum series, improved per 3.6.

Every graphic has the same data contract: `{template, team(s), metric values, baseline values, window, evidence ids}`. The existing cue schema can carry it.

---

## 8. What already exists in the repo that we'd reuse

- `schemas/match_event.schema.json`: event shape, zones and qualifiers already fit (pass difficulty, `pressure_on_passer`, `line_breaking`, ball speed).
- `swing/stats/`: metrics, momentum, win probability, contribution; a starting point for the aggregator.
- Match-State MCP server, Verifier, Director attention budget, Translator, cue schema and the live Azure pipeline: all still apply; only the "moment" source changes from big events to tactical states.

---

## 9. Questions for the design step

1. **Generator:** build the script-driven possession-chain generator (6.1), or keep feeding from the current simulator?
2. **What drives an overlay:** state changes only, or also a timed "quiet spell" slot every few minutes?
3. **How many graphic templates for the demo:** I'd suggest 5 to 6 (control meter, territory, press line, tempo dial, attack lanes, before/after).
4. **What sits behind the overlays on screen:** a blank broadcast frame, a static stadium image, or the existing 2D pitch with no players?
5. **Personalisation:** analyst mode shows the raw numbers and baselines; casual mode shows only the meter and one number. Does that still fit?

---

## Sources

- Opta / The Analyst, Premier League playing styles 2024-25 (direct speed, build-up attacks, high turnovers, transition passes): https://theanalyst.com/articles/analysing-premier-league-playing-styles-2024-25
- Stats Perform, sequences and the Premier League: https://www.statsperform.com/resource/sequences-and-the-premier-league
- Stats Perform, how we measure pressure: https://www.statsperform.com/insights/how-we-measure-pressure/
- Wyscout glossary, PPDA: https://dataglossary.wyscout.com/ppda/
- Sportmonks glossary (field tilt, key data points): https://www.sportmonks.com/glossary/key-data-points
- Bundesliga Match Facts, attacking zones and most pressed player: https://www.bundesliga.com/en/bundesliga/news/new-match-facts-aws-attacking-zones-most-pressed-player-position-trends-14713
- Bundesliga Match Facts, match momentum: https://www.bundesliga.com/en/bundesliga/news/bundesliga-match-facts-aws-match-momentum-34052
- Flashscore, Opta Match Momentum explained: https://www.flashscore.com/news/momentum/W82o7eCa/
- Defector, "What on earth is match momentum": https://defector.com/what-on-earth-is-match-momentum
- FIFA Enhanced Football Intelligence (phases of play): https://www.fifatrainingcentre.com/media/native/world-cup-2022/Enhanced%20Football%20Intelligence%20EN.pdf
- socceraction StatsBomb event schema (counterpress, under_pressure): https://socceraction.readthedocs.io/en/stable/api/generated/socceraction.data.statsbomb.StatsBombEventSchema.html
- Fernandez-Navarro et al. (2016), Attacking and defensive styles of play in soccer, *J Sports Sci* 34(24): https://researchonline.ljmu.ac.uk/id/eprint/3791/
- Expected threat (xT), Karun Singh (original blog post; grid size not re-verified today), summarised at: https://metricgate.com/docs/ja/expected-threat-xt-soccer/
