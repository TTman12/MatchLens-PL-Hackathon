# The broadcast screen

![The user screen: club crests, the squad on a pitch, the controls in the feed](img/user-screen.png)

![A card and the followed player's strip, expanded](img/expanded.png)

![Full screen: the feed fills the screen, the graphics keep their size](img/full-screen.png)

![A card on a substitute's running, with the club stats panel](img/broadcast.png)

![The MatchLens analysis card that follows: what the side that lost momentum could do](img/analysis.png)

The screen in `web/` plays a match on a condensed clock. By default 1 match minute takes 1.6 seconds, so a full match runs about 2.5 minutes. It is laid out like a stream, over a photo of a stadium. There are two screens:

- **User** (the default): for fans. The right side is a picker instead of stats: **Your club** as crests for the two clubs playing (and Neutral) with the name under each, the chosen one lifted and highlighted, and **Your player**: choose either team and its squad appears on a pitch, fantasy-football style, one line each for goalkeeper, defenders, midfield and attack, with the bench below. Each player is a card with a blank profile picture, his position and his name; the chosen one is highlighted and followed. Play, the speed, the language and full screen sit in a control bar along the bottom of the feed, as on a video player, and fade while the match plays. The user screen plays the match it was opened on (`?match=`); the match list and Generate match are on the admin screen. Full screen fills the screen with the feed, with the momentum history (above the line for the home side, below for the away side) slim along its bottom; the cards and strips keep the size they had, rather than growing with the monitor. The crests are drawn by the page from each club's colours (a shape, a pattern and an initial); there are no real marks or photos.
- **Admin** (`?mode=admin`, the button in either screen, or M): the operator's screen, described below, with the stats tabs and what the agents did.

Both screens share the feed, the cards and the momentum bar:

- **The feed** (top left). A still of the stadium stands in for the match video. Over it sit:
  - **the score and clock**;
  - **the cards**, as a lower third, which pop up when the Director puts one on screen. A card shows:
    - its anchor, such as "Since Dunmoor goal 25'", or, when no event started it, how long it has been going on: "Last 5 minutes", "Last 10 minutes" or "Last 15 minutes" (the nearest to the window the stats cover);
    - one line saying what the numbers mean for the game, written for the viewer's club ([explainer.md](explainer.md));
    - one big number, against the same team before the anchor. For a substitute, the comparison is with the player they replaced. Where it can, the card pairs two stats that explain each other, rather than showing a lone possession figure. Each number reads as one line and one path: a colour chip for the club, then "Brackenford's progressive passes" (or "Corvcombe's distance vs Brennow" for a substitute), then the number before (small and faded), an arrow and the number now (big and solid). The numbers show which way it went, so there are no extra symbols, and the momentum bar along the bottom of the screen shows momentum, so the card doesn't repeat it.
    - an **Expand** button. The card starts simple; Expand keeps the line and puts a short table where the big number was: the cause the agents settled on, momentum before and now, and four stats for both clubs before the anchor and since (the card's own stats first, then the ones that moved most). An open card stays up until it is closed.
  - **notifications**, in the middle of the feed, since there is no picture to watch: "Goal · Dunmoor" with the scorer, every substitution (who came on and off) and every red card, as they happen, and with each momentum card a "Momentum shift" or "Big momentum shift" (a swing of 40 points or more in the home side's share) towards the club that gained it, so the card never arrives cold. One at a time, a few seconds each, in English or Spanish, only for what the clock has reached.
  - **the MatchLens analysis**, which follows a card when it leaves: what a club could do about the momentum, the take fans argue about. The side that lost it gets "How Dunmoor win it back" ("Dunmoor need to push the line back up and stop inviting Calderwick on"); the side that has it gets "How Calderwick keep it going". A fan of either club sees their own club's; a neutral sees the side that lost momentum. Under the line is the stat behind it. Every idea is backed by a stat in the match ([agents.md](agents.md), step 5).
  - **the full-time recap**, which takes over the feed at the final whistle (or press F): the score and one headline for the viewer's club, who had the game in each quarter-hour (the home side's share of momentum, as a bar in the two clubs' colours), the three turning points (the cards whose momentum swung most), full-time stat pairs as two-sided bars, and a standout player for each club with the stat that sets them apart. Expand adds xG and duels won, the momentum swing at each turning point, and the first half against the second.
  - **follow a player**, when a player is followed: a strip under the score with his name and three live numbers (touches, passes, distance); its Expand button adds pass accuracy, duels won and sprints. Name tags pop out beside it when something happens (a goal, an assist, a shot, a card, coming on or off) or a running total reaches a set threshold (5 and 10 km covered, 10, 20 and 30 sprints, 25, 50 and 75 passes, 5 and 10 duels won, 5, 10 and 15 defensive actions). His moments sit on the timeline, a card stat about him is outlined, and at full time the recap shows where he finished in his team on each stat and his touches across the match.
- **Stats panel** (right, admin screen):
  - **Your club**: neutral or either side. The card sentence is written for that club's fans. The choice is remembered on this device.
  - **EN or ES**: English or Spanish. Every label on screen, every card anchor and stat label, and every line is in the chosen language. The Spanish lines are translations of the English ones, checked in code, or the rules' own Spanish when a translation fails its check ([agents.md](agents.md), step 7). The language is remembered on this device.
  - **Clubs**: six stats as two-sided bars at the current minute; Expand shows all 24 for both sides, the leader in bold, with a "last 15 minutes" column for each club. Tap a club to see its players.
  - **Players**: every player who has played, and for each one 14 stats at the current minute. Open a player and press Follow to follow him.
  - **Agents**: what the agents did for the card on screen: each specialist's verdict, the Explainer's reason, whether the Verifier passed the card, and how the Interpreter and the Analyst did.

  Distance and sprints are modelled from tracking-style data, and are marked so.
- **Momentum and timeline** (bottom):
  - The momentum bar: the home side's share of final-third play over the last few minutes, as a gradient in the two clubs' colours. It is always on.
  - Goals, red cards and substitutions sit above the line for the home side and below it for the away side.
  - The momentum history fills in above the line as the match plays.

Card types are **goal**, **red card**, **substitution**, **half-time**, **momentum shift** and **recovery**.

The page does no analysis. `matchlens-broadcast` runs the Watcher, the specialists, the Explainer and the Director, and writes one JSON bundle per match to `web/data/`. With `--agents foundry`, the agent crew on Microsoft Foundry explains each moment instead ([agents.md](agents.md)). Each card then carries the agents' log, which the Agents tab of the stats panel shows.

Each bundle also carries the recap, follow-a-player and the Spanish screen (`matchlens/broadcast/extras.py`). `--enrich` adds them to the bundles already in `--out`, keeping their cards and the agents' lines; with `--agents foundry` the Recapper and Translator run too, and `--translator azure|agent|offline` picks the translation backend (by default, Azure AI Translator when `AZURE_TRANSLATOR_KEY` is set, else the Translator agent on Foundry).

```
matchlens-broadcast --demo 6 --out web/data            # six fresh generated matches
matchlens-broadcast --demo 6 --out web/data --enrich --agents foundry   # recap + Spanish on the bundles there
matchlens-broadcast --demo 6 --out web/data --agents foundry   # explained by the agents on Foundry
matchlens-broadcast out/matches/ash-brk-7 --out web/data   # or any match folder
cd web && python3 -m http.server 8000                    # then open http://localhost:8000
matchlens-live --web web --agents offline                # the same, plus Generate match (docs/generate-match.md)
```

**URL options:** `?match=<id>`, `&speed=1|2|4`, `&autoplay=1`, `&hide=1` to hide the operator controls for screen capture, `&tab=clubs|players|agents` to open a panel tab, `&mode=user|admin`, `&fan=<team id>` to pick the viewer's club, `&lang=en|es`, `&follow=<player id>` to follow a player, and `&open=1` to bring every card up expanded.

**Keys:**
- Space: play or pause.
- N: jump to the next card.
- R: restart.
- H: hide the controls.
- U: switch between the Agents tab and the Clubs tab.
- F: jump to full time and the recap.
- E: expand or close the card on screen.
- M: switch between the user and admin screens.
- L: switch between English and Spanish.

Click the timeline to scrub.

## Look

- **Colours:** primary `#28002b`, secondary `#ffffff`, accent `#0000ee`. Team colours come from the fictional clubs. When two sides' colours are too close, the away side switches to its second colour.
- **Type:** headings in the PremierLeague typeface at 700 (an H1 is 32px on a 1920-wide screen). That typeface is licensed, so it is not in this repo: the page uses it when it is installed, or when it is placed at `web/assets/fonts/PremierLeague.woff2`. Otherwise Barlow and Barlow Condensed stand in.
- **Stadium:** `web/assets/stadium.jpg`, a photo Tristan supplied. Its boards and stands carry no marks. No league or club marks appear on screen.

## The Director

The Director is `matchlens/explain/director.py`. The pipeline raises about 12 candidate cards a match, and the Director keeps about 6:
- A card needs at least one number and something worth showing.
- Cards are at least 5 minutes apart. A goal or red-card card may break that gap.
- At most 5 cards go up per half.
- It decides as each card arrives and never waits to see a later one, so it chooses the same way on a live feed as on a recorded match. When several cards arrive in the same minute, the most urgent, then the most salient, goes first.

Individual players appear on a card only when the card is about them: a substitute against the player they replaced, or a player on the side that gained who is clearly doing more (see [explainer.md](explainer.md)). A player's row leads with his name, then the stat. A "usual" needs at least 12 minutes of match before the anchor, so an early goal gets no card rather than a misleading one.
