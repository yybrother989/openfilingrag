"""Normalized agent event protocol.

Events are emitted by graph nodes and streamed to the frontend over SSE.
The frontend renders structured cards keyed on `type`. Keep this contract
stable — changing it breaks UI components.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventType(str, Enum):
    """All event types the workflow may emit.

    Order matters for the UI — events of the same `type` may appear
    multiple times (e.g. `node_start`/`node_end` per node, `evidence_found`
    once per evidence item).
    """

    RUN_STARTED = "run_started"
    NODE_START = "node_start"
    NODE_END = "node_end"
    QUERY_CLASSIFIED = "query_classified"
    RETRIEVAL_PLAN = "retrieval_plan"
    SECTION_SELECTED = "section_selected"
    EVIDENCE_FOUND = "evidence_found"
    VERIFICATION_WARNING = "verification_warning"
    TOKEN = "token"
    REPORT_SECTION = "report_section"
    FINAL_REPORT = "final_report"
    RUN_COMPLETED = "run_completed"
    ERROR = "error"


class AgentEvent(BaseModel):
    """A single event emitted during workflow execution.

    The same shape is used regardless of `type`; the `payload` carries
    type-specific data. This keeps the SSE wire-format trivial to parse
    on the frontend.
    """

    model_config = ConfigDict(use_enum_values=True)

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    thread_id: str | None = None
    timestamp: datetime = Field(default_factory=_utcnow)
    type: EventType
    node: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> str:
        """Serialize as a Server-Sent-Events frame.

        Format::

            event: <type>
            id: <event_id>
            data: <json>

        """
        body = self.model_dump(mode="json")
        body["timestamp"] = self.timestamp.isoformat()
        return (
            f"event: {self.type if isinstance(self.type, str) else self.type.value}\n"
            f"id: {self.event_id}\n"
            f"data: {json.dumps(body, separators=(',', ':'))}\n\n"
        )
