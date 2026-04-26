"""Event emitter — bridges synchronous LangGraph nodes to async SSE streams.

A single :class:`EventEmitter` is created per streaming workflow run on the
asyncio loop that will consume it. Worker-thread producers call
:meth:`emit` (non-blocking) and the queue is drained by :meth:`stream`.
"""

from __future__ import annotations

import asyncio
import contextvars
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from app.schemas.events import AgentEvent, EventType

_current_emitter: contextvars.ContextVar["EventEmitter | None"] = contextvars.ContextVar(
    "current_emitter", default=None
)


class EventEmitter:
    """Per-run event channel. Producers call ``emit``; consumers iterate ``stream``."""

    SENTINEL = object()

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        run_id: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        self.run_id = run_id or str(uuid.uuid4())
        self.thread_id = thread_id
        self._loop = loop
        # Construct the queue on the consumer's loop so put_nowait scheduled
        # via call_soon_threadsafe runs in the loop's thread.
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._closed = False

    def emit(
        self,
        type: EventType,
        payload: dict[str, Any] | None = None,
        node: str | None = None,
    ) -> None:
        if self._closed:
            return
        evt = AgentEvent(
            run_id=self.run_id,
            thread_id=self.thread_id,
            timestamp=datetime.now(timezone.utc),
            type=type,
            node=node,
            payload=payload or {},
        )
        if not self._loop.is_running():
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, evt)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, self.SENTINEL)

    async def stream(self) -> AsyncIterator[AgentEvent]:
        """Yield events until ``close`` is called."""
        while True:
            item = await self._queue.get()
            if item is self.SENTINEL:
                return
            yield item


def set_current_emitter(emitter: EventEmitter | None) -> contextvars.Token:
    return _current_emitter.set(emitter)


def reset_current_emitter(token: contextvars.Token) -> None:
    _current_emitter.reset(token)


def get_current_emitter() -> EventEmitter | None:
    return _current_emitter.get()


def emit(
    type: EventType,
    payload: dict[str, Any] | None = None,
    node: str | None = None,
) -> None:
    """Emit an event to the current run's emitter, if one is bound.

    Safe to call from any node — silently no-ops in non-streaming mode.
    """
    em = _current_emitter.get()
    if em is not None:
        em.emit(type, payload, node)
