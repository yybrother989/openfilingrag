"""LangGraph workflow assembly.

A single compiled :class:`StateGraph` is the source of truth for node
order. Both execution paths run *through* it:

* :func:`run_workflow` — synchronous wrapper around ``graph.invoke``,
  used by ``POST /research/query`` and tests. Workflow events emitted
  via :func:`app.graph.streaming.emit` are silently dropped here (no
  stream consumer).
* :func:`stream_workflow` — async generator that drives
  ``graph.astream`` and translates LangGraph's native ``custom`` /
  ``values`` channels back into our :class:`AgentEvent` shape for SSE.

Per-run services (DB session, chat model, retriever) are injected into
nodes via ``RunnableConfig.configurable.node_context``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.schemas.events import AgentEvent, EventType
from app.schemas.graph_state import GraphState
from app.schemas.query import ResearchQuery

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
    from langchain_core.language_models.chat_models import BaseChatModel
    from sqlalchemy.orm import Session

    from app.retrieval.evidence_store import EvidenceStore
    from app.retrieval.hybrid_retriever import HybridRetriever

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

    Topology is mostly linear, with a ``validate_report → generate_report``
    self-correction loop. The conditional edge fires when the validate
    node sets ``state.revision_required`` (e.g. a finding lacks citations
    or cites an unknown source_id) and ``revision_count < MAX_REVISIONS``.

    Nodes are wrapped with :func:`make_langgraph_adapter` so the original
    ``(state, ctx)`` signature still works for unit tests, while the
    graph itself sees the LangGraph-native ``(state, config)`` shape.
    """
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(GraphState)
    for name, fn in NODE_ORDER:
        graph.add_node(name, make_langgraph_adapter(name, fn))

    graph.add_edge(START, "classify_query")
    graph.add_edge("classify_query", "plan_retrieval")
    graph.add_edge("plan_retrieval", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "verify_evidence")
    graph.add_edge("verify_evidence", "generate_report")
    graph.add_edge("generate_report", "validate_report")
    graph.add_conditional_edges(
        "validate_report",
        lambda s: "generate_report" if s.revision_required else "format_output",
        {"generate_report": "generate_report", "format_output": "format_output"},
    )
    graph.add_edge("format_output", END)

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
    chat_model: "BaseChatModel",
    retriever: "HybridRetriever",
    evidence_store: "EvidenceStore | None" = None,
) -> GraphState:
    """Execute the workflow via ``graph.invoke`` and return the final state.

    Used directly by ``POST /research/query`` and tests. Streaming
    events are no-ops because there is no stream consumer attached.
    """
    state = GraphState(user_query=query)
    ctx = NodeContext(
        session=session,
        chat_model=chat_model,
        retriever=retriever,
        evidence_store=evidence_store,
    )
    config = {"configurable": {"node_context": ctx}}

    try:
        result = get_graph().invoke(state, config)
        return _coerce_state(result, state)
    except Exception as e:
        log.exception("workflow.invoke failed", err=str(e))
        state.errors.append(f"workflow: {e}")
        return state


# ---------------------------------------------------------------------
# Async streaming execution (FastAPI SSE)
# ---------------------------------------------------------------------
async def stream_workflow(
    query: ResearchQuery,
    *,
    session: "Session",
    chat_model: "BaseChatModel",
    retriever: "HybridRetriever",
    evidence_store: "EvidenceStore | None" = None,
    thread_id: str | None = None,
) -> AsyncIterator[AgentEvent]:
    """Drive ``graph.astream`` and yield :class:`AgentEvent`s.

    Cancellation is asyncio-native: cancelling the consumer task
    propagates into ``astream`` and stops the graph between nodes.
    In-flight nodes (typically a sync LLM call) still finish.
    """
    run_id = str(uuid.uuid4())
    state = GraphState(user_query=query)
    ctx = NodeContext(
        session=session,
        chat_model=chat_model,
        retriever=retriever,
        evidence_store=evidence_store,
    )
    config = {"configurable": {"node_context": ctx, "thread_id": thread_id}}

    yield AgentEvent(
        run_id=run_id,
        thread_id=thread_id,
        type=EventType.RUN_STARTED,
        payload={"query": query.query, "ticker": query.ticker},
    )

    final_state: GraphState = state
    cancelled = False
    try:
        async for mode, chunk in get_graph().astream(
            state,
            config,
            stream_mode=["custom", "values"],
        ):
            if mode == "custom":
                # Re-hydrate AgentEvent from the writer payload that
                # streaming.emit() produced inside the node.
                try:
                    evt_type = EventType(chunk.get("event"))
                except ValueError:
                    log.warning("unknown event type in stream", event=chunk.get("event"))
                    continue
                yield AgentEvent(
                    run_id=run_id,
                    thread_id=thread_id,
                    type=evt_type,
                    node=chunk.get("node"),
                    payload=chunk.get("payload") or {},
                )
            elif mode == "values":
                # Last "values" chunk is the final GraphState snapshot.
                final_state = _coerce_state(chunk, state)
    except (asyncio.CancelledError, GeneratorExit):
        cancelled = True
        # Surface the cancellation as a final event before re-raising so
        # the SSE consumer sees a clean close.
        yield AgentEvent(
            run_id=run_id,
            thread_id=thread_id,
            type=EventType.RUN_COMPLETED,
            payload={"cancelled": True},
        )
        raise
    except Exception as e:
        log.exception("astream failed", err=str(e))
        yield AgentEvent(
            run_id=run_id,
            thread_id=thread_id,
            type=EventType.ERROR,
            payload={"error": str(e)},
        )

    if not cancelled:
        yield AgentEvent(
            run_id=run_id,
            thread_id=thread_id,
            type=EventType.RUN_COMPLETED,
            payload={
                "report_id": (
                    final_state.final_report.report_id
                    if final_state.final_report
                    else None
                ),
                "errors": list(final_state.errors),
                "warnings": list(final_state.validation_warnings),
            },
        )
