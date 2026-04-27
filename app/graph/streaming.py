"""Workflow-event emitter — thin wrapper over LangGraph's
:func:`~langgraph.config.get_stream_writer`.

Replaces the hand-rolled :class:`~app.graph.event_emitter.EventEmitter`
+ contextvar + ``ThreadPoolExecutor`` bridge that used to plumb events
from sync nodes to the SSE consumer. LangGraph 1.x ships a per-run
stream writer accessible from any node via ``get_stream_writer()``;
:func:`stream_workflow` consumes the ``"custom"`` channel of
``graph.astream(...)`` and translates each writer payload back into the
project's :class:`~app.schemas.events.AgentEvent` shape.

The wire format is unchanged — every emit produces a dict with keys
``{event, node, payload}`` so :func:`stream_workflow` can rebuild the
same ``AgentEvent`` the frontend already expects.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.schemas.events import EventType

log = get_logger(__name__)


def emit(
    event_type: EventType,
    payload: dict[str, Any] | None = None,
    *,
    node: str | None = None,
) -> None:
    """Emit a workflow event to the active LangGraph stream writer.

    Silently no-ops outside a runnable context (unit tests that bypass
    the graph; the synchronous ``run_workflow`` path with no SSE
    consumer; nodes called directly from a debugger). Keeps the keys
    stable: ``stream_workflow`` rebuilds an ``AgentEvent`` from
    ``{event, node, payload}`` so changing them breaks the API layer.
    """
    try:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
    except (RuntimeError, ImportError):
        return
    if writer is None:
        return
    try:
        writer({
            "event": event_type.value if hasattr(event_type, "value") else str(event_type),
            "node": node,
            "payload": payload or {},
        })
    except Exception as e:
        # Never let an emit problem break the actual workflow execution.
        log.debug("stream emit failed", err=str(e))
