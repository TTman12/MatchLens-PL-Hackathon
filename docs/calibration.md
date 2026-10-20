# Simulator calibration

Per-match averages from 380 simulated matches (random pairings of the 20 fictional clubs,
`--seed 1`), compared with ranges typical of a top-flight European league season. The
ranges are approximate, drawn from widely published season averages, and are there to
catch a simulator that drifts out of football's shape, not to claim precision.

| Statistic | Simulated (380 matches) | Target range | In range |
|---|---|---|---|
| Goals per match | 2.70 | 2.40 to 3.20 | yes |
| Shots per match | 26.97 | 21.00 to 28.00 | yes |
| Shots on target per match | 9.05 | 7.00 to 10.00 | yes |
| Average xG per shot | 0.12 | 0.09 to 0.13 | yes |
| Passes per match (open play and restarts) | 879.04 | 800.00 to 1050.00 | yes |
| Pass completion | 79.5% | 78.0% to 86.0% | yes |
| Corners per match | 10.59 | 8.50 to 11.50 | yes |
| Fouls per match | 18.18 | 18.00 to 25.00 | yes |
| Yellow cards per match | 3.68 | 3.00 to 4.50 | yes |
| Red cards per match (straight or second yellow) | 0.19 | 0.05 to 0.25 | yes |
| Offsides per match | 3.16 | 2.50 to 5.00 | yes |
| Throw-ins per match | 33.07 | 32.00 to 50.00 | yes |
| Home wins | 44.7% | 40.0% to 50.0% | yes |
| Draws | 22.4% | 20.0% to 30.0% | yes |
| Ball in play, minutes | 58.60 | 52.00 to 62.00 | yes |
| Match length incl. added time, minutes | 98.60 | 93.00 to 101.00 | yes |
| xG per match (both teams) | 3.18 | no target | |
| Big chances (xG 0.30 or more) per match | 3.43 | no target | |
| Goal kicks per match | 14.14 | no target | |
| Tackles per match | 34.40 | no target | |

Rows marked "no target" are reported for transparency. About one shot in nine goes in,
and goals run a little under xG because the keeper's rating and the shooter's finishing
both act on top of it. Big chances sit near the roughly four per match often quoted.

Rerun it after changing any tuning constant in `matchlens/sim/engine.py` or
`matchlens/sim/models.py` (about fifteen minutes):

```bash
matchlens-sim calibrate --matches 380 --report docs/calibration.md
```

`tests/test_sim.py` checks looser versions of the same ranges over 24 matches on every
push.
