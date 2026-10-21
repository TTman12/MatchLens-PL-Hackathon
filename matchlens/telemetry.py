"""Tracing the agent runs with OpenTelemetry, into Azure Application Insights.

Every match gets one trace. The code steps (Watcher, Verifier, fallback) are spans of their own,
and the Foundry agents' calls hang underneath them. Microsoft Agent Framework adds those calls as
``invoke_agent`` and ``chat`` spans, following the OpenTelemetry GenAI conventions:

    matchlens.match ash-brk-31
      matchlens.watcher                      moments=9
      matchlens.moment 63:00                 mode=shift gainer=brk
        matchlens.specialist team_play       verdict=relevant
          invoke_agent matchlens-team-play
            chat gpt-4.1-mini
            execute_tool investigate_team_play
        ...
        matchlens.explainer round=1          verifier=passed
      matchlens.interpreter / matchlens.analyst

The traces go to the Application Insights resource linked to the Foundry project. The connection
string comes from ``APPLICATIONINSIGHTS_CONNECTION_STRING`` if that is set, otherwise from the
project itself, so the Foundry portal's Tracing page shows each run with no other setup.
``MATCHLENS_TRACING=off`` turns tracing off. ``MATCHLENS_TRACE_CONTENT=0`` leaves prompts and
replies out of the traces (all the data is synthetic, so they are kept by default).

Nothing here is required: without the OpenTelemetry packages (the ``foundry`` extra) a span is
a no-op, which is how the offline runner and CI use it.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from typing import Any

log = logging.getLogger(__name__)

CONNECTION_VAR = "APPLICATIONINSIGHTS_CONNECTION_STRING"
SERVICE = "matchlens-agents"

_state: dict[str, Any] = {"exporting": False}


class _AgentFrameworkTracesTheModel(logging.Filter):
    """Drops azure-ai-projects' note that its own experimental GenAI tracing is off. It is left off
    on purpose: Agent Framework already traces every agent and model call, and turning both on would
    record each call twice."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING" not in record.getMessage()


def _attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """OpenTelemetry takes str, bool, int, float and lists of those; drop the rest."""
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        if isinstance(v, str | bool | int | float):
            out[f"matchlens.{k}"] = v
        elif isinstance(v, list | tuple) and all(isinstance(x, str) for x in v):
            out[f"matchlens.{k}"] = list(v)
    return out


@contextlib.contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    """A span under the current one. It yields a setter ``note(**attrs)``, for results known
    only at the end of the step."""
    try:
        from opentelemetry import trace
    except ImportError:
        yield lambda **_: None
        return
    with trace.get_tracer("matchlens").start_as_current_span(f"matchlens.{name}", attributes=_attrs(attrs)) as s:
        yield lambda **more: s.set_attributes(_attrs(more))


async def connect(project_client: Any | None = None) -> bool:
    """Send traces to Application Insights, once per process. True if they are being sent."""
    if _state["exporting"] is not False or os.environ.get("MATCHLENS_TRACING", "").lower() == "off":
        return _state["exporting"] is True  # set up already (or being set up, or failed): once per process
    _state["exporting"] = None  # tried; don't try again in this process
    conn = os.environ.get(CONNECTION_VAR, "").strip()
    if not conn and project_client is not None:
        try:
            conn = await project_client.telemetry.get_application_insights_connection_string()
        except Exception as exc:  # no linked resource, or no right to read it: run untraced
            log.info("no Application Insights connection on the Foundry project (%s); not tracing", exc)
    if not conn:
        return False
    try:
        from agent_framework.observability import enable_instrumentation
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        log.info("tracing needs the 'foundry' extra: pip install -e '.[foundry]'")
        return False
    os.environ.setdefault("OTEL_SERVICE_NAME", SERVICE)
    logging.getLogger("azure.ai.projects.telemetry._ai_project_instrumentor").addFilter(_AgentFrameworkTracesTheModel())
    try:
        configure_azure_monitor(connection_string=conn, logger_name="matchlens")
        enable_instrumentation(enable_sensitive_data=os.environ.get("MATCHLENS_TRACE_CONTENT", "1") != "0")
    except Exception as exc:  # tracing is a nice-to-have: never let it stop a run
        log.warning("could not start tracing (%s); running untraced", exc)
        return False
    _state["exporting"] = True
    log.info("tracing agent runs to Application Insights")
    return True


def flush() -> None:
    """Push out buffered spans; a CLI run exits right after the last one ends."""
    try:
        from opentelemetry import trace
    except ImportError:
        return
    provider = trace.get_tracer_provider()
    try:
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception as exc:  # a failed export must not fail the run that produced it
        log.warning("could not send the last traces (%s)", exc)
