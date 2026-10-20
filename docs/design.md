# MatchLens: Momentum Explainer design (draft for Tristan)

Status: draft, 20 Oct 2026. Nothing has been built yet.

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
| Anchor label | "Since A. Johnson red card" / "Since the double sub" | "Since 63'" (when the change started) [Choice: anchor to the start of the change rather than a fixed 15 min] |
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

These are built on the existing stack (Agent Framework, Foundry prompt agents, the Match-State MCP server, Verifier, Translator, cue feed). Specialists call **deterministic tools** for every number; the LLM reasons, compares and chooses, and never does arithmetic.

| Agent | Role | Reads |
|---|---|---|
| **Watcher** (master) | Runs continuously. Keeps the momentum series against a long baseline (match so far plus expected level for strength and game state). Fires on (a) any discrete event, (b) a sustained shift above the noise floor, or (c) a recovery. Assigns the mode and the anchor time. | team_minute, events |
| **Team-play analyst** | What changed in team behaviour since the anchor: pass share, defending height, directness, duel share, accuracy by third, PPDA. Ranks changes by effect size against both the team's own baseline and random-window spread. | team_minute |
| **Player analyst** | Which individuals changed: biggest movers in duels, defensive actions, involvement and physical output. Flags fatigue fades. | player_minute |
| **Substitutions analyst** | Each sub since the anchor: incoming player against the player he replaced (rates per minute), and whether the team's change lines up with his zone or role. Must be willing to say "not me". | player_minute, events |
| **Match-events analyst** | Goals, cards and game state: score effects (a trailing team pushing), a 10-man reshape, a leading team managing the game. | events, team_minute |
| **Explainer** (selector) | Collects the findings, decides the cause chain, and picks the **1 or 2 stats** that best show it plus the anchor label. It prefers numbers that are both large and easy for a fan to read. It may conclude "no clear single cause". | all findings |
| **Verifier** | Recomputes every number from the tables, and rejects anything that doesn't match or lacks evidence. (Exists already.) | tables |
| **Director** | Decides when the graphic goes on screen: quiet spell, attention budget, cooldown. (Exists already.) | cue queue |
| **Translator** | Translates labels only, since there are no sentences. (Exists already.) | cue |

**Shared state.** Each finding is one record: `{agent, claim_type, metric, team or player, before, after, effect_sd, confidence, evidence_ids}`. The record is shared through the MCP server so that every agent sees the others' findings. That shared-state handoff is what the multi-agent judges look for.

**Failure recovery.** If a specialist times out, the Explainer works with what it has and lowers its confidence. If the Verifier rejects a number, the Explainer must pick the next-best stat. Both paths are shown in the existing "under the hood" drawer.

## 6. Graphic contract

```json
{
  "mode": "event | spontaneous | recovery",
  "anchor": {"label": "Since A. Johnson red card", "t": 3720, "event_id": "m042-e0811"},
  "stats": [
    {"label": "Possession", "team": "ash", "before": 54, "after": 31, "unit": "%"},
    {"label": "Defending height", "team": "ash", "before": 41, "after": 28, "unit": "m"}
  ],
  "momentum": {"before": 0.12, "now": -0.38, "home": "ash", "away": "bry"},
  "cause": {"kind": "red_card_reshape", "confidence": 0.8},
  "evidence": ["m042-e0811", "..."],
  "duration_s": 12
}
```

On screen this reads: the anchor label, 1 or 2 before → after numbers, and the momentum bar moving from before to now. Analyst mode can open an evidence panel. Casual mode shows only the bar and one number.

## 7. How we score it (the evaluation story)

On 100 or more generated matches with hidden truth:
- **Cause accuracy:** for each fired graphic, does the Explainer's cause chain match the truth?
- **False blame:** how often it credits an event that truth says changed nothing. This should be low.
- **Abstention:** on swings that truth marks as noise or recovery, does it say so?
- **Number accuracy:** Verifier pass rate (target 100%).
- **Timeliness:** minutes from the change starting to the graphic going up.

These sit beside the realism gate as the two headline charts for the judges.

## 8. What carries over from the current repo

- **Keep:** the fictional league and clubs, the event schema, the agent framework and Foundry roster, the MCP server, the Verifier, the Director, the Translator, the cue feed, the live Azure site and CI.
- **Drop or freeze:** the movement simulator, 10 Hz frames, and the camera and replay system.
- **Change:**
  - the stats engine gains `team_minute`, `player_minute` and the long-baseline Watcher;
  - the current Moment Detector becomes the Watcher.

## 9. Open questions for Tristan

1. **What sits behind the graphics in the demo?** Options are a static broadcast-style frame, the existing 2D pitch with no players, or a simple "match feed" of the score and clock.
2. **Physical stats (distance, sprints):** include them as modelled and labelled, or leave them out?
3. **Graphic styles for the first build:** I'd start with three: the event-mode card, the spontaneous-mode card, and the recovery card.
4. **Build order:** I'd do the generator first and gate it on the realism test, then the Watcher and specialists, then the graphics.

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
