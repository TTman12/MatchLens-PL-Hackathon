"""Match-State MCP server exposing match, season and stats tools.

``tools.MatchStateStore`` holds the lookups; ``server.build_server`` publishes them over
MCP. The agents call the same store in-process. Owned by the AGT track.
"""

from .tools import TOOL_NAMES, MatchStateStore

__all__ = ["TOOL_NAMES", "MatchStateStore"]
