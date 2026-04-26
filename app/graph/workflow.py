"""LangGraph workflow assembly.

A single compiled :class:`StateGraph` is the source of truth for node
order. Both execution paths run *through* it:

* :func:`run_workflow` — synchronous wrapper around ``graph.invoke``,
  used by ``POST /research/query`` and tests.
* :func:`stream_workflow` — async generator that runs ``graph.invoke`` on
  a thread pool and pipes events out through :class:`EventEmitter` for
  ``POST /research/stream`` (SSE).

Per-run services (DB session, LLM, retriever, cancel signal) are
injected into nodes via ``RunnableConfig.configurable.node_context``.
LangGraph wraps every invoke/astream call with its own callback manager,
so LangSmith tracing kicks in automatically when ``LANGSMITH_API_KEY`` is
set — no extra wiring needed.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.schemas.events import AgentEvent, EventType
from app.schemas.graph_state import GraphState
from app.schemas.query import ResearchQuery
from app.schemas.report import ResearchReport

from .event_emitter import (
    EventEmitter,
    reset_current_emitter,
    set_current_emitter,
)
from .nodes import (
    NodeContext,
    classify_query,
    format_output,
    generate_report,
    make_langgraph_adapter,
    plan_retrieval,
    retrieve_evidence,
    validate_report,
    verify_evidence,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.retrieval.evidence_store import EvidenceStore
    from app.retrieval.hybrid_retriever import HybridRetriever
    from app.services.llm_service import LLMService

log = get_logger(__name__)

NODE_ORDER = [
    ("classify_query", classify_query),
    ("plan_retrieval", plan_retrieval),
    ("retrieve_evidence", retrieve_evidence),
    ("verify_evidence", verify_evidence),
    ("generate_report", generate_report),
    ("validate_report", validate_report),
    ("format_output", format_output),
]


# ---------------------------------------------------------------------
# Compiled LangGraph (cached at module level)
# ---------------------------------------------------------------------
def build_langgraph():
    """Build & compile the StateGraph.

    Nodes are wrapped with :func:`make_langgraph_adapter` so the original
    ``(state, ctx)`` signature still works for unit tests, while the
    graph itself sees the LangGraph-native ``(state, config)`` shape.
    """
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(GraphState)
    for name, fn in NODE_ORDER:
        graph.add_node(name, make_langgraph_adapter(name, fn))

    graph.add_edge(START, NODE_ORDER[0][0])
    for i, (name, _) in enumerate(NODE_ORDER[:-1]):
        graph.add_edge(name, NODE_ORDER[i + 1][0])
    graph.add_edge(NODE_ORDER[-1][0], END)

    return graph.compile()


_GRAPH = None


def get_graph():
    """Return the cached compiled graph; built lazily on first use."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_langgraph()
    return _GRAPH


def _coerce_state(result, fallback: GraphState) -> GraphState:
    """LangGraph may return a Pydantic instance or a dict-like — normalize."""
    if isinstance(result, GraphState):
        return result
    if isinstance(result, dict):
        for k, v in result.items():
            if hasattr(fallback, k):
                setattr(fallback, k, v)
        return fallback
    return fallback


# ---------------------------------------------------------------------
# In-process synchronous execution
# ---------------------------------------------------------------------
def run_workflow(
    query: ResearchQuery,
    *,
    session: "Session",
    llm: "LLMService",
    retriever: "HybridRetriever",
    evidence_store: "EvidenceStore | None" = None,
    emitter: EventEmitter | None = None,
    cancel_event: threading.Event | None = None,
) -> GraphState:
    """Execute the workflow via LangGraph and return the final state.

    Used directly by ``POST /research/query`` and tests. If ``emitter``
    is provided, nodes can emit events to it via the contextvar-bound
    :func:`app.graph.event_emitter.emit` helper. Cancellation is
    cooperative — set ``cancel_event`` to ask the workflow to stop
    between nodes (the current node finishes; subsequent ones short-
    circuit in their ``_wrap`` decorator).
    """
    cancel = cancel_event or threading.Event()
    state = GraphState(user_query=query)
    ctx = NodeContext(
        session=session,
        llm=llm,
        retriever=retriever,
        evidence_store=evidence_store,
        cancel_event=cancel,
    )
    config = {"configurable": {"node_context": ctx}}

    token = set_current_emitter(emitter) if emitter else None
    try:
        if emitter:
            emitter.emit(
                EventType.RUN_STARTED,
                {"query": query.query, "ticker": query.ticker},
            )

        try:
            result = get_graph().invoke(state, config)
            final_state = _coerce_state(result, state)
        except Exception as e:
            log.exception("workflow.invoke failed", err=str(e))
            state.errors.append(f"workflow: {e}")
            final_state = state

        if emitter:
            if cancel.is_set():
                emitter.emit(EventType.RUN_COMPLETED, {"cancelled": True})
            else:
                emitter.emit(
                    EventType.RUN_COMPLETED,
                    {
                        "report_id": final_state.final_report.report_id
                        if final_state.final_report
                        else None,
                        "errors": final_state.errors,
                        "warnings": final_state.validation_warnings,
                    },
                )
    finally:
        if token is not None:
            reset_current_emitter(token)
    return final_state


# ---------------------------------------------------------------------
# Async streaming execution (FastAPI SSE)
# ---------------------------------------------------------------------
async def stream_workflow(
    query: ResearchQuery,
    *,
    session: "Session",
    llm: "LLMService",
    retriever: "HybridRetriever",
    evidence_store: "EvidenceStore | None" = None,
    thread_id: str | None = None,
    cancel_event: threading.Event | None = None,
) -> AsyncIterator[AgentEvent]:
    """Yield :class:`AgentEvent`s as the workflow runs.

    LangGraph's :class:`StateGraph` is the executor; we run
    ``graph.invoke`` on a worker thread and let nodes pump events back
    via :class:`EventEmitter` (which they reach through the
    contextvar-bound module-level :func:`emit` helper). Pass
    ``cancel_event`` to allow the caller — typically the SSE endpoint's
    disconnect watcher — to ask the workflow to stop between nodes.
    """
    run_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    emitter = EventEmitter(loop=loop, run_id=run_id, thread_id=thread_id)
    cancel = cancel_event or threading.Event()

    def _runner() -> ResearchReport | None:
        try:
            final_state = run_workflow(
                query,
                session=session,
                llm=llm,
                retriever=retriever,
                evidence_store=evidence_store,
                emitter=emitter,
                cancel_event=cancel,
            )
            return final_state.final_report
        finally:
            emitter.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = loop.run_in_executor(pool, _runner)
        try:
            async for evt in emitter.stream():
                yield evt
        except (asyncio.CancelledError, GeneratorExit):
            cancel.set()
            emitter.close()
            raise
        try:
            await fut
        except Exception as e:
            err = AgentEvent(
                run_id=run_id,
                thread_id=thread_id,
                type=EventType.ERROR,
                payload={"error": str(e)},
            )
            yield err
