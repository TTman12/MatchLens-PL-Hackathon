# MatchLens: Momentum Explainer design

Status: written as a draft on 20 Oct 2026 before anything was built, and brought up to date on 21 Oct 2026. Everything below is now built. Sections 1 to 4 and 7 are the design as agreed; sections 5, 6 and 8 describe what was built where it differs from the draft; section 10 holds Tristan's decisions. For how each part works today, the per-part docs are the reference: [agents.md](agents.md), [explainer.md](explainer.md), [broadcast.md](broadcast.md), [generator.md](generator.md), [live-feed.md](live-feed.md) and [generate-match.md](generate-match.md).

This builds on two earlier files:
- `docs/research/football-stats-for-tactical-inference.md`, for the metric vocabulary;
- `docs/research/real-momentum-patterns.md`, for what 380 real matches show.

**[Real]** marks a number measured from the 2017-18 Wyscout data. **[Choice]** marks a design decision that is open to change.

## 1. The product in one line

Everyone can see when the tide turns; MatchLens shows *why*. Agents watch every team and player stat minute by minute. When something changes, they find where it came from and put up a graphic with 1 or 2 numbers and a momentum bar, with no sentences on screen.

## 2. The two modes

| | **Event mode** | **Spontaneous mode** |
|---|---|---|
| Trigger | A discrete event: goal, red card, substitution, half-time, injury | A detected shift (or recovery) with no event that explains it |
| Anchor label | "Since A. Johnson red card" / "Since the double sub" | "Last 7 minutes": the real window since the change started, not rounded to 5, 10 or 15 |
| Question the agents answer | What changed after the event, and did momentum move? | What changed in play, and what kind of cause does it look like (instruction, fatigue, a duel battle turning, opponent adjustment)? |
| Momentum outcome | Any. "No shift, the block is holding" is a valid graphic. | A shift or recovery by definition |
| Real frequency | Events barely raise the chance of a sustained shift: 22 to 29% after an event against 21% after a random minute [Real] | About 30% of shifts have no event in the 15 minutes before [Real] |

**Recovery** is a third label inside spontaneous mode [Real: many short-window shifts are bounce-backs from a dip]. Example: "Back to their level after a 10-minute wobble".

## 3. Data model (what the generator emits and the agents read)

All of it is fictional (we reuse the existing fictional league and clubs) and synthetic. There are three public tables and one hidden table.

1. **`events`**: one row per on-ball action, using the existing `match_event` schema. Every number on screen can cite these ids.
2. **`team_minute`**: one row per team per minute (≈ 2 × 95 rows per match).
   - **Possession and passing:** passes attempted and completed, by third; progressive passes; long balls.
   - **Territory:** final-third and box entries, field-tilt events.
   - **Out of possession:** defensive actions and their mean height; duels and duels won; high turnovers.
   - **Attack and discipline:** shots, xG, xT, fouls and cards.
   - **Context:** ball-in-play seconds and the score.
3. **`player_minute`**: one row per player on the pitch per minute (≈ 22 × 95 rows).
   - **On the ball:** touches by third, passes attempted and completed, progressive passes.
   - **Duels and defending:** duels and duels won, tackles, interceptions, mean x of defensive actions.
   - **Attack and discipline:** shots, xG, fouls.
   - **Physical [modelled, labelled as such]:** distance in metres, high-speed metres and sprints.
   - **State:** on the pitch, position or role.
   - **Rule:** team rows are always the sum of player rows.
4. **`truth`** (hidden from the agents, used only for evaluation):
   - the plan timeline per team: behaviour parameters per minute;
   - every decision, with its trigger (an event id or "spontaneous") and kind (instruction, fatigue, substitution impact, red-card reshape, game management);
   - the expected direction of the effect.

## 4. Generator

The principle comes from Tristan: **momentum is never written directly.** Events may cause a change of plan. Plans set how a team plays. Stats come out of play. Momentum comes out of the stats.

Layers:

1. **Team identity.** Style parameters per club:
   - block height, press intensity, directness, tempo, width, risk, duel aggression, and base quality.
   - [Choice] Start the archetypes from the spread of real 2017-18 teams, measured from the data (for example possession-heavy, direct, low-block counter), then map them onto our fictional clubs.
2. **Player model.** Each player has:
   - a role, an ability and a stamina curve.
   - Fatigue gradually lowers his duel rate, pressing and physical output. Per-player activity dips at 60 to 75 minutes [Real].
   - A substitute comes on fresh: +22% duels per minute and +12% on-ball events compared with the player he replaced [Real].
3. **Play engine (per minute, both teams together).**
   - Possessions are generated as chains over pitch zones.
   - Action choice and success depend on *both* teams' current plans: one team's high press against the other's build-up raises turnovers in that zone.
   - Possession share, territory and momentum therefore emerge from the interaction.
   - Noise is calibrated so matches wobble around a level the way real ones do: about 5.6 short-window shifts per match, many of them recoveries [Real].
4. **Decision layer.** This is where causes come from.
   - **After an event,** there is a probability of a plan change, drawn from real effects:
     - A red card leads to a deeper block in about 73% of cases [Real].
     - A conceding team pushes up about 10 field-tilt points on average [Real].
     - A losing side's sub adds about 4 points on average [Real], with a wide spread.
   - **Spontaneous changes,** with no event:
     - coach instructions at random times (a step change in directness or pressing);
     - fatigue thresholds (a gradual fade);
     - "duel battle turning" (one side's duel win rate drifts).
   - **The opponent can respond:** counter-adjust, or not.
   - Every decision is logged to `truth`.
5. **Output.** The tables in section 3 are streamed minute by minute for live mode, or written out whole for replay.

**Realism gate.** Before anything else uses the generator, generate 380 fictional matches and compare them with the real season on every number in `docs/research/real-momentum-patterns.md`. That covers:
- passes, accuracy, shots, goals, cards and subs per match;
- shifts per match, against the noise floor;
- the share of shifts with no trigger;
- event follow-through rates;
- the red-card style change and the substitute boost;
- the lead-lag dip.

A metric passes if it falls inside the real spread. The comparison chart becomes the realism evidence in the demo.

## 5. Agents

As built. The agents run on Microsoft Foundry through Microsoft Agent Framework. Specialists call **deterministic tools** for every number; the models reason, compare and choose, and never do arithmetic. Code decides when to act, what is allowed and what reaches the screen. The full crew, with each agent's checks, is in [agents.md](agents.md).

| Agent | Kind | Role | Reads |
|---|---|---|---|
| **Watcher** | code | Keeps the momentum scale (the home side's share of final-third touches). Fires on a sustained shift, a recovery, or a discrete event, from 20' on, and never looks ahead. Assigns the mode and the anchor. | team_minute, events |
| **Team-play analyst** | Foundry agent + tool | What changed in team behaviour since the anchor across 21 stats, ranked by effect size against random windows of the same match. | team_minute |
| **Player analyst** | Foundry agent + tool | Which individuals changed most, and a team-wide fatigue fade. | player_minute |
| **Substitutions analyst** | Foundry agent + tool | Each sub since the anchor against the player he replaced. Must be willing to say "not me". | player_minute, events |
| **Match-events analyst** | Foundry agent + tool | Goals, cards and game state: a trailing team pushing, a 10-man reshape, a leading team managing the game. | events, team_minute |
| **Explainer** | Foundry agent | Reads the findings board, picks a cause from those the evidence allows and the **1 or 2 stats** that best show it. It may conclude there's no clear single cause. | the board |
| **Verifier** | code | Re-runs the specialists on the tables, compares every number and enforces the screen rules. A rejected draft goes back once, then the rules' card is used. | tables |
| **Director** | code | Decides on the spot whether a card goes on screen: 5 minutes apart, 5 a half, goals and reds can break in. | cards |
| **Interpreter** | Foundry agent | One line per viewer (neutral and each club's fans) on what the card means for the game, held to the facts by a check in code. | the verified card |
| **Analyst** | Foundry agent | The MatchLens analysis card: what each club could do, picked from levers a stat backs. | the verified card |
| **Recapper** | Foundry agent | The full-time headline per viewer. | the recap facts |
| **Translator** | Foundry agent or Azure AI Translator | Every on-screen line in Spanish, checked in code for names and numbers. Labels and anchors use a fixed glossary. | the bundle's lines |

**Shared state.** Each finding is one record on the findings board (`matchlens/agents/board.py`): `{id, agent, claim_type, metric, team or player, before, after, effect_sd, polarity, ...}`. Every specialist posts to it and the Explainer reads it; models refer to findings by id, so the number on screen is always the tool's number. The draft planned to share the board through an MCP server; it is shared in process instead, and there is no MCP server on the crew's path.

**Failure recovery.** If a specialist fails or times out, the Explainer works with what it has and the card's confidence drops by 0.1 per missing specialist. If the Verifier rejects a draft, it goes back once with the problems listed; a second miss falls back to the deterministic choice. The Interpreter, Analyst, Recapper and Translator agent each get one retry and then fall back to the rules' lines (the Azure AI Translator backend falls back straight away). Every step is logged on the card and shown in the admin screen's Agents tab.

## 6. Graphic contract

As built, one card in a match bundle (`web/data/<match>.json`, written by `matchlens-broadcast`), trimmed:

```json
{
  "at": 27, "clock": "27'", "kind": "shift", "tag": "Momentum shift",
  "anchor": "Last 9 minutes", "anchor_m": 18,
  "stats": [
    {"label": "Passes in own half", "team": "brk", "player": null, "value": "62%", "usual": "73%", "usual_label": "before", "unit": "of passes", "rise": false},
    {"label": "Passes in final third", "team": "brk", "player": null, "value": "6", "usual": "2", "window": "in 9 min", "rise": true}
  ],
  "momentum": {"before": 84.9, "now": 63.6, "gainer": "brk"},
  "cause": "play_change", "story": "pushing_up",
  "text": {"neutral": "...", "ash": "...", "brk": "..."},
  "analysis": {"...": "the MatchLens analysis card that follows"},
  "detail": {"...": "the expanded table"},
  "hood": {"runner": "foundry", "specialists": ["..."], "verifier": ["..."], "confidence": 0.71},
  "i18n": {"es": {"anchor": "Últimos 9 minutos", "text": {"...": "..."}}}
}
```

`kind` is one of goal, red card, substitution, half-time, shift and recovery. On screen a card reads as the anchor, one line for the viewer's club, and one big before → after number. It starts simple for a casual fan; **Expand** opens the analyst's view: the cause, momentum before and now, and four stats for both clubs. The momentum bar along the bottom of the screen shows the swing, so the card doesn't repeat it. Each card is timed (`at`) and machine-readable, so it could drive a graphics engine over a real feed as well as our screen.

## 7. How we score it (the evaluation story)

On 100 or more generated matches with hidden truth:
- **Cause accuracy:** for each fired graphic, does the Explainer's cause chain match the truth?
- **False blame:** how often it credits an event that truth says changed nothing. This should be low.
- **Abstention:** on swings that truth marks as noise or recovery, does it say so?
- **Number accuracy:** Verifier pass rate (target 100%).
- **Timeliness:** minutes from the change starting to the graphic going up.

These sit beside the realism gate as the two headline charts for the judges.

## 8. What changed from the draft

- **Clean slate.** The old repo (movement simulator, 10 Hz frames, camera and replay, the earlier Match-State MCP server) was wiped on 20 Oct. It stays in git history only.
- **A new, smaller MCP server.** The agents' tools (investigate, read the board, check a card) are served by the MatchLens MCP server, in process, with a fallback to direct calls. The same server runs on stdio for outside tools. See [agents.md](agents.md#the-mcp-server).
- **The Translator translates sentences,** not just labels, because each card now has a line written for the viewer. A check in code compares each translation with the English.
- **Agents after the card.** The Interpreter, the Analyst and the Recapper were added so the screen can say what a card means, what a club could do about it, and how the match went, each held to the facts by code and screened by Azure AI Content Safety.
- **Strictly live.** The Watcher and the Director decide minute by minute with no look-ahead, so a recorded match and a live feed give the same cards ([live-feed.md](live-feed.md)). A feed adapter takes another provider's per-minute tables, and Generate match on the live site plays brand-new matches through the agents ([generate-match.md](generate-match.md)).
- **Two screens.** A fan screen (pick a club crest and a player on a pitch, video-player controls) and an admin screen (stats, the agents' log, the match list, Generate match), plus notifications for goals, subs, reds and momentum shifts, follow-a-player, the full-time recap and Spanish ([broadcast.md](broadcast.md)).

## 9. Open questions (answered)

1. **What sits behind the graphics?** A stadium still (section 10, point 5).
2. **Physical stats?** Included, modelled and labelled as modelled.
3. **First graphic styles?** Event, spontaneous and recovery cards, all built.
4. **Build order?** Generator first, gated on the realism test; all four steps are done.

## 10. Decisions (Tristan, 20 Oct 11:53)

1. **Clean slate.** Wipe the old repo and start again. Keep only the licence and housekeeping files; everything old stays in git history.
2. **Any match, not scripted.** A full match file is fed straight in, and the agents work it out on their own for any match.
   - The agents never see `truth`, and nothing in the agents may know about planted causes.
   - Test on unseen seeds and team styles.
   - Publish the input format so any data that matches it works.
3. **Baseline for explaining a shift.** Compare stats since the shift began against the team's average over the whole match so far, excluding the shift period itself.
4. **Settling period.** No shift detection or explanation before 20'. Events before then still go on the timeline, and an event-mode card for an early event (e.g. a red at 12') waits until there is enough data after it.
5. **Screen layout:**
   - A realistic stadium still (a freeze-frame of a match in play) fills the background. Nothing is simulated.
   - A **momentum scale** is always visible.
   - An **event timeline** runs along the bottom (goals, cards, subs, half-time).
   - The **score and clock** stay.
   - The **cards** pop up broadcast-style, like the PL's possession lower-thirds: event, spontaneous and recovery.
6. **Distance and sprints:** included, modelled, and labelled as modelled.
7. **Build order:** generator first, gated on the realism test.
8. **Look:**
   - Emulate the Premier League's broadcast and website visual language (colour, type feel, layout, motion) rather than default AI-site styling. No logos.
   - Open point for the graphics stage: the PL typeface is proprietary, and the rules bar third-party trademarks. Plan to use a close open-licence font and a palette inspired by theirs, not exact brand assets.
9. **Stadium image:**
   - Ideally AI-generated with an image model on Azure (this also strengthens the Microsoft story).
   - It needs a paid image-model deployment, so get Tristan's OK first.
   - Otherwise, a licence-free stock photo with no club branding.
