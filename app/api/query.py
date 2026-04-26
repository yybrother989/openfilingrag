"""Research query endpoints — sync (/research/query) and SSE (/research/stream).

The streaming endpoint emits the normalized agent-event protocol so the
frontend can render structured cards (classification, retrieval plan,
evidence found, verification warnings, final report) in real time.
"""

from __future__ import annotations

import asyncio
import json
import threading

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.session import get_db, session_scope
from app.graph.policies import REFUSAL_MESSAGE, is_advice_query
from app.graph.workflow import run_workflow, stream_workflow
from app.retrieval.evidence_store import EvidenceStore
from app.schemas.evidence import EvidenceItem
from app.schemas.query import ResearchQuery
from app.schemas.report import ResearchReport
from app.services.report_service import get_workflow_deps

router = APIRouter(tags=["research"])
log = get_logger(__name__)


# ---------------------------------------------------------------------
# Sync endpoint
# ---------------------------------------------------------------------
@router.post("/research/query", response_model=ResearchReport)
def research_query(
    body: ResearchQuery,
    session: Session = Depends(get_db),
) -> ResearchReport:
    deps = get_workflow_deps()
    state = run_workflow(
        body,
        session=session,
        llm=deps.llm,
        retriever=deps.retriever,
        evidence_store=deps.evidence_store,
    )
    if state.final_report is None:
        if state.errors:
            raise HTTPException(status_code=500, detail="; ".join(state.errors))
        raise HTTPException(status_code=500, detail="workflow returned no report")
    return state.final_report


# ---------------------------------------------------------------------
# Streaming endpoint (SSE)
# ---------------------------------------------------------------------
@router.post("/research/stream")
async def research_stream(body: ResearchQuery, request: Request) -> StreamingResponse:
    """Stream agent events as SSE.

    Note: we open a *fresh* DB session inside the generator so it lives
    for the whole stream (FastAPI's Depends-injected session would close
    when the route returns). This matches FastAPI's recommendation for
    long-lived streams.
    """
    deps = get_workflow_deps()

    # Cheap pre-guard: refuse advice queries before opening a stream.
    if is_advice_query(body.query):
        async def _refusal():
            from app.schemas.events import AgentEvent, EventType

            yield AgentEvent(
                run_id="refused",
                type=EventType.RUN_STARTED,
                payload={"query": body.query, "ticker": body.ticker},
            ).to_sse()
            yield AgentEvent(
                run_id="refused",
                type=EventType.QUERY_CLASSIFIED,
                payload={
                    "intent": "refused_advice",
                    "refused": True,
                    "reason": "advice question",
                    "message": REFUSAL_MESSAGE,
                    "ticker": body.ticker,
                    "company_name": body.company_name,
                    "fiscal_year": body.fiscal_year,
                    "document_ids": body.document_ids,
                },
            ).to_sse()
            yield AgentEvent(
                run_id="refused",
                type=EventType.RUN_COMPLETED,
                payload={"refused": True, "message": REFUSAL_MESSAGE},
            ).to_sse()

        return StreamingResponse(
            _refusal(),
            media_type="text/event-stream",
            headers={"X-OpenFilingRAG-Refused": "true"},
        )

    async def event_generator():
        cancel_event = threading.Event()

        async def disconnect_watcher() -> None:
            # Poll even when no events flow — a long LLM call would
            # otherwise let the client sit disconnected for ~30s while
            # we keep burning tokens.
            try:
                while not cancel_event.is_set():
                    if await request.is_disconnected():
                        log.info("client disconnected, signalling cancel")
                        cancel_event.set()
                        return
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                pass

        watcher = asyncio.create_task(disconnect_watcher())
        with session_scope() as session:
            try:
                async for event in stream_workflow(
                    body,
                    session=session,
                    llm=deps.llm,
                    retriever=deps.retriever,
                    evidence_store=deps.evidence_store,
                    cancel_event=cancel_event,
                ):
                    if cancel_event.is_set():
                        return
                    yield event.to_sse()
            except asyncio.CancelledError:
                log.info("stream cancelled")
                cancel_event.set()
                raise
            finally:
                cancel_event.set()
                watcher.cancel()

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )


# ---------------------------------------------------------------------
# Evidence lookup
# ---------------------------------------------------------------------
@router.get("/evidence/{source_id}", response_model=EvidenceItem)
def get_evidence(source_id: str, session: Session = Depends(get_db)) -> EvidenceItem:
    store = EvidenceStore()
    item = store.get(session, source_id)
    if not item:
        raise HTTPException(status_code=404, detail="evidence not found")
    return item


# ---------------------------------------------------------------------
# Sample questions (for the demo UI's quick-start panel)
# ---------------------------------------------------------------------
@router.get("/research/sample_questions")
def sample_questions() -> dict:
    from app.evaluation.sample_questions import SAMPLE_QUESTIONS

    return {"questions": SAMPLE_QUESTIONS}
