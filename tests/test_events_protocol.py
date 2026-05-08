"""Agent event protocol: serialization + emit no-op behaviour.

Phase 5 deleted the hand-rolled :class:`EventEmitter` so most of this
file's old surface area is gone. What we still care about:

  * :class:`AgentEvent` round-trips and serializes as the SSE wire
    format the frontend depends on.
  * :func:`app.graph.streaming.emit` silently no-ops when called
    outside a LangGraph runnable context — the synchronous workflow
    path and unit tests rely on this.

End-to-end ordering of events through ``stream_workflow`` is covered by
``tests/test_graph_workflow.py``.
"""

from __future__ import annotations

import json

import pytest

from app.graph.streaming import emit
from app.schemas.events import AgentEvent, EventType


def test_event_serializes_as_sse() -> None:
    evt = AgentEvent(
        run_id="r1",
        type=EventType.QUERY_CLASSIFIED,
        payload={"intent": "risk_analysis", "ticker": "ACME"},
    )
    sse = evt.to_sse()
    assert sse.startswith("event: query_classified\n")
    assert "id: " in sse
    assert sse.endswith("\n\n")

    data_line = next(ln for ln in sse.splitlines() if ln.startswith("data:"))
    data = json.loads(data_line[len("data:"):].strip())
    assert data["payload"]["ticker"] == "ACME"
    assert data["type"] == "query_classified"


@pytest.mark.parametrize("etype", list(EventType))
def test_all_event_types_round_trip(etype) -> None:
    evt = AgentEvent(run_id="r", type=etype, payload={"k": 1})
    rebuilt = AgentEvent.model_validate_json(
        AgentEvent.model_validate(evt.model_dump(mode="json")).model_dump_json()
    )
    rebuilt_type = rebuilt.type.value if hasattr(rebuilt.type, "value") else rebuilt.type
    assert rebuilt_type == etype.value


def test_emit_outside_runnable_context_does_not_raise() -> None:
    """``streaming.emit`` is called from many places in nodes; if it ever
    raises outside a LangGraph run it would take the whole workflow
    down. The wrapper must swallow the ``RuntimeError`` from
    ``get_stream_writer()``."""
    emit(EventType.RUN_STARTED, {"query": "ignored"}, node="test")
    emit(EventType.NODE_END, None, node="classify_query")
    # No assertion needed — the test passes by not raising.
