"""The Match-State MCP server.

Exposes the Match-State tools over the Model Context Protocol, so the agents, GitHub
Copilot in VS Code or any MCP client can ask about the match: moments, player and
season stats, the table, fixtures, win probability, contribution shares and momentum.

Run it over stdio against a match folder (and, optionally, the agents' moments):

    matchlens-mcp data/sample --moments out/sample/moments.json

or over streamable HTTP for a hosted deployment:

    matchlens-mcp data/sample --transport streamable-http
"""

from __future__ import annotations

import argparse
from typing import Any

from mcp.server.mcpserver import MCPServer

from .tools import MatchStateStore

INSTRUCTIONS = (
    "Match-State tools for one synthetic football match in a fictional league. "
    "Times are match seconds since kick-off on one continuous timeline. Facts returned in "
    "'facts' are verified and can be cited as evidence."
)


def build_server(store: MatchStateStore) -> MCPServer:
    server = MCPServer(name="matchlens-match-state", instructions=INSTRUCTIONS, version="0.1.0")

    @server.tool()
    def get_match() -> dict[str, Any]:
        """Teams, stadium, stakes and pre-match win probability for the streamed match."""
        return store.get_match()

    @server.tool()
    def list_moments() -> list[dict[str, Any]]:
        """Every detected moment so far: id, type, time, importance and swing."""
        return store.list_moments()

    @server.tool()
    def get_moment(moment_id: str) -> dict[str, Any]:
        """The full moment record, e.g. moment_id 'm017-mo02'."""
        return store.get_moment(moment_id)

    @server.tool()
    def get_player_match_stats(player_id: str, t: float | None = None) -> dict[str, Any]:
        """A player's match so far (player_id like 'ash-09'), optionally up to match time t."""
        return store.get_player_match_stats(player_id, t)

    @server.tool()
    def get_season_stats(player_id: str) -> dict[str, Any]:
        """A player's league season before this match."""
        return store.get_season_stats(player_id)

    @server.tool()
    def get_table(live_at_t: float | None = None) -> dict[str, Any]:
        """The table before kick-off, or the live table at match time live_at_t."""
        return store.get_table(live_at_t)

    @server.tool()
    def get_fixtures(team_id: str) -> dict[str, Any]:
        """A club's fixtures (team_id like 'ash') and its next match."""
        return store.get_fixtures(team_id)

    @server.tool()
    def win_probability(
        t: float, score_home: int | None = None, score_away: int | None = None
    ) -> dict[str, Any]:
        """Win probability and suspense at match time t, at the real or a what-if score."""
        return store.win_probability(t, score_home, score_away)

    @server.tool()
    def get_contribution(shot_event_id: str) -> dict[str, Any]:
        """Contribution shares for the move that ended in a shot (event id like 'm017-e0026')."""
        return store.get_contribution(shot_event_id)

    @server.tool()
    def get_momentum(t: float) -> dict[str, Any]:
        """Threat points for each side over the five minutes to t, and momentum from -1 to 1."""
        return store.get_momentum(t)

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("match_dir", help="Folder with match.json, events.json, frames.jsonl ...")
    parser.add_argument("--moments", help="moments.json written by matchlens-agents")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    args = parser.parse_args(argv)
    store = MatchStateStore.from_dir(args.match_dir, args.moments)
    build_server(store).run(args.transport)


if __name__ == "__main__":  # pragma: no cover
    main()
