# The broadcast screen

![A half-time card written for Brackenford fans, with the club stats panel](img/broadcast.png)

The screen in `web/` plays a match on a condensed clock. By default 1 match minute takes 1.6 seconds, so a full match runs about 2.5 minutes. It is laid out like a stream, over a blurred photo of a stadium:

- **The feed** (top left). A still of the stadium stands in for the match video. Over it sit:
  - **the score and clock**;
  - **the cards**, as a lower third, which pop up when the Director puts one on screen. A card shows:
    - its anchor, such as "Since Dunmoor goal 25'" or "Since 63'";
    - one sentence saying what changed in the way a team plays, written for the viewer's club ([explainer.md](explainer.md));
    - one or two numbers, each against the same team before the anchor. For a substitute, the comparison is with the player they replaced. Where it can, the card pairs two stats that explain each other, rather than showing a lone possession figure;
    - a momentum bar with both clubs' codes, a gradient from one club's colour to the other's, and a faded line where momentum was before the bar moves to now.
- **Stats panel** (right):
  - **Your club**: neutral or either side. The card sentence is written for that club's fans. The choice is remembered on this device.
  - **Clubs**: 24 stats for both sides at the current minute, the leader in bold. Tap a club to see its players.
  - **Players**: every player who has played, and for each one 14 stats at the current minute.
  - **Agents**: what the agents did for the card on screen: each specialist's verdict, the Explainer's reason, and whether the Verifier passed the card.

  Distance and sprints are modelled from tracking-style data, and are marked so.
- **Momentum and timeline** (bottom):
  - The momentum bar: the home side's share of final-third play over the last few minutes, as a gradient in the two clubs' colours. It is always on.
  - Goals, red cards and substitutions sit above the line for the home side and below it for the away side.
  - The momentum history fills in above the line as the match plays.

Card types are **goal**, **red card**, **substitution**, **half-time**, **momentum shift** and **recovery**.

The page does no analysis. `matchlens-broadcast` runs the Watcher, the specialists, the Explainer and the Director, and writes one JSON bundle per match to `web/data/`. With `--agents foundry`, the agent crew on Microsoft Foundry explains each moment instead ([agents.md](agents.md)). Each card then carries the agents' log, which the Agents tab of the stats panel shows.

```
matchlens-broadcast --demo 6 --out web/data            # six fresh generated matches
matchlens-broadcast --demo 6 --out web/data --agents foundry   # explained by the agents on Foundry
matchlens-broadcast out/matches/ash-brk-7 --out web/data   # or any match folder
cd web && python3 -m http.server 8000                    # then open http://localhost:8000
```

**URL options:** `?match=<id>`, `&speed=1|2|4`, `&autoplay=1`, `&hide=1` to hide the operator controls for screen capture, `&tab=clubs|players|agents` to open a panel tab, and `&fan=<team id>` to pick the viewer's club.

**Keys:**
- Space: play or pause.
- N: jump to the next card.
- R: restart.
- H: hide the controls.
- U: switch between the Agents tab and the Clubs tab.

Click the timeline to scrub.

## Look

- **Colours:** primary `#28002b`, secondary `#ffffff`, accent `#0000ee`. Team colours come from the fictional clubs. When two sides' colours are too close, the away side switches to its second colour.
- **Type:** headings in the PremierLeague typeface at 700 (an H1 is 32px on a 1920-wide screen). That typeface is licensed, so it is not in this repo: the page uses it when it is installed, or when it is placed at `web/assets/fonts/PremierLeague.woff2`. Otherwise Barlow and Barlow Condensed stand in.
- **Stadium:** `web/assets/stadium.jpg`, from a photo Tristan supplied, with the crest and the advertising boards blurred out. No league or club marks appear on screen.

## The Director

The Director is `matchlens/explain/director.py`. The pipeline raises about 12 candidate cards a match, and the Director keeps about 6:
- A card needs at least one number and something worth showing.
- Cards are at least 5 minutes apart. A goal or red-card card may break that gap.
- At most 5 cards go up per half.
- When candidates compete within those 5 minutes, the most salient one wins.

Individual players appear on a card only when the card is about them: a substitute against the player they replaced, or a player on the side that gained who is clearly doing more (see [explainer.md](explainer.md)). A player's row leads with his name, then the stat. A "usual" needs at least 12 minutes of match before the anchor, so an early goal gets no card rather than a misleading one.
