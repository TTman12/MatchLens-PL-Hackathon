# The broadcast screen

![A goal card on the broadcast screen](img/broadcast.png)

The screen in `web/` plays a match on a condensed clock. By default 1 match minute takes 1.6 seconds, so a full match runs about 2.5 minutes. It shows four things over a freeze-frame of a stadium:

- **Score and clock** (top left).
- **Momentum scale** (top right): the home side's share of final-third play over the last few minutes. It is always on.
- **Timeline** (bottom):
  - Goals, red cards and substitutions sit above the line for the home side and below it for the away side.
  - The momentum history fills in above the line as the match plays.
- **Cards** (lower third), which pop up when the Director puts one on screen. A card shows:
  - its anchor, such as "Since Dunmoor goal 25'" or "Since 63'";
  - one or two numbers, each against the match average up to the anchor. For a substitute, the comparison is with the player they replaced;
  - a momentum bar that slides from before to now.

Card types are **goal**, **red card**, **substitution**, **half-time**, **momentum shift** and **recovery**.

The page does no analysis. `matchlens-broadcast` runs the Watcher, the specialists, the Explainer and the Director, and writes one JSON bundle per match to `web/data/`. With `--agents foundry`, the agent crew on Microsoft Foundry explains each moment instead ([agents.md](agents.md)). Each card then carries the agents' log, which the under-the-hood panel shows.

```
matchlens-broadcast --demo 6 --out web/data            # six fresh generated matches
matchlens-broadcast --demo 6 --out web/data --agents foundry   # explained by the agents on Foundry
matchlens-broadcast out/matches/ash-brk-7 --out web/data   # or any match folder
cd web && python3 -m http.server 8000                    # then open http://localhost:8000
```

**URL options:** `?match=<id>`, `&speed=1|2|4`, `&autoplay=1`, `&hide=1` to hide the operator controls for screen capture, and `&hood=1` to open the under-the-hood panel.

**Keys:**
- Space: play or pause.
- N: jump to the next card.
- R: restart.
- H: hide the controls.
- U: under the hood. For the card on screen, it shows each specialist's verdict, the Explainer's reason, and whether the Verifier passed the card.

Click the timeline to scrub.

## Look

The colour, type and layout take after Premier League broadcast graphics:
- deep purple panels;
- green, cyan and pink accents;
- condensed capitals;
- hard-edged lower thirds that wipe in.

It uses open fonts (Barlow and Barlow Condensed) and no league or club marks. Team colours come from the fictional clubs. When two sides' colours are too close, the away side switches to its second colour.

**Stadium still:** put a 16:9 image at `web/assets/stadium.jpg` and it replaces the drawn backdrop.

## The Director

The Director is `matchlens/explain/director.py`. The pipeline raises about 12 candidate cards a match, and the Director keeps about 6:
- A card needs at least one number and something worth showing.
- Cards are at least 5 minutes apart. A goal or red-card card may break that gap.
- At most 5 cards go up per half.
- When candidates compete within those 5 minutes, the most salient one wins.

Individual players appear on a card only when the card is about them, such as a substitute against the player they replaced. A single player's busy five minutes is noise next to what the team did. A "usual" needs at least 12 minutes of match before the anchor, so an early goal gets no card rather than a misleading one.
