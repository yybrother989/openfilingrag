"""Agent event protocol: serialization + emitter behaviour."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.graph.event_emitter import EventEmitter
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

    # Extract the data line and validate it's valid JSON
    data_line = next(ln for ln in sse.splitlines() if ln.startswith("data:"))
    data = json.loads(data_line[len("data:"):].strip())
    assert data["payload"]["ticker"] == "ACME"
    assert data["type"] == "query_classified"


def test_emitter_streams_events_then_closes() -> None:
    async def run() -> list[AgentEvent]:
        em = EventEmitter(loop=asyncio.get_running_loop(), run_id="r2")
        em.emit(EventType.RUN_STARTED, {"q": "hi"})
        em.emit(EventType.NODE_START, {"node": "classify_query"}, node="classify_query")
        em.emit(EventType.NODE_END, {"node": "classify_query"}, node="classify_query")
        em.close()
        return [e async for e in em.stream()]

    events = asyncio.run(run())
    types = [e.type for e in events]
    types_str = [t.value if hasattr(t, "value") else str(t) for t in types]
    assert types_str == ["run_started", "node_start", "node_end"]
    assert all(e.run_id == "r2" for e in events)


@pytest.mark.parametrize(
    "etype",
    list(EventType),
)
def test_all_event_types_round_trip(etype) -> None:
    evt = AgentEvent(run_id="r", type=etype, payload={"k": 1})
    rebuilt = AgentEvent.model_validate_json(
        AgentEvent.model_validate(evt.model_dump(mode="json")).model_dump_json()
    )
    rebuilt_type = rebuilt.type.value if hasattr(rebuilt.type, "value") else rebuilt.type
    expected = etype.value
    assert rebuilt_type == expected
