# MatchLens

**Everyone can see when the tide turns. MatchLens shows why.**

MatchLens watches every team and player statistic minute by minute. When a match changes, it finds out where the change came from and puts it on screen as a broadcast graphic: one or two numbers and a momentum bar, with no sentences. The change can follow an event (a red card, a substitution, a goal) or happen with no event at all (a change of instructions, tiredness, a duel battle turning).

It is a fresh start for the Microsoft × Premier League hackathon. All match data is synthetic and the clubs are fictional.

## Status

This is a clean slate. The plan and the evidence behind it:

- [docs/design.md](docs/design.md): the design, including the two modes, the data model, the generator, the agents, the graphic contract and the scoring.
- [docs/research/football-stats-for-tactical-inference.md](docs/research/football-stats-for-tactical-inference.md): which football stats exist and what each one reveals about how a team is playing.
- [docs/research/real-momentum-patterns.md](docs/research/real-momentum-patterns.md): what 380 real matches show about momentum shifts. The synthetic data is tested against these numbers.

## Build order

1. Synthetic match generator, gated on a realism test against the real-season patterns.
2. A watcher that spots shifts, plus specialist agents that investigate them.
3. Broadcast graphics: a momentum scale, an event timeline, and the event, spontaneous and recovery cards.

## Research data

`research/` holds the scripts that measured the real-season patterns. They read the public Wyscout event dataset (Pappalardo et al., 2019, *Scientific Data* 6:236, [figshare](https://doi.org/10.6084/m9.figshare.c.4415000), CC BY 4.0). That data is downloaded on demand to measure patterns only. None of it is committed or shipped.

## Licence

MIT. See [LICENSE](LICENSE).
