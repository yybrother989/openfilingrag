"""End-to-end workflow test using fakes.

The retriever is stubbed to return a curated evidence list; the LLM is the
``MockProvider`` (deterministic JSON). This validates that nodes wire up
correctly and produce a valid ``ResearchReport``.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import pytest

from app.graph.workflow import run_workflow, stream_workflow
from app.schemas.document import (
    CanonicalSection,
    ContentType,
    DocumentType,
    SourcePriority,
)
from app.schemas.evidence import EvidenceItem
from app.schemas.events import EventType
from app.schemas.query import ResearchIntent, ResearchQuery


@dataclass
class _StubRetriever:
    items: list[EvidenceItem]

    def retrieve(self, session, query, plan, k=None):  # noqa: D401, ARG002
        return list(self.items)


def _evidence(section: str, text: str, score: float = 0.8) -> EvidenceItem:
    return EvidenceItem(
        source_id=str(uuid.uuid4()),
        document_id=1,
        chunk_index=0,
        ticker="ACME",
        company_name="Acme Corp",
        document_type=DocumentType.TEN_K,
        fiscal_year=2025,
        source_priority=SourcePriority.PRIMARY_FILING,
        section=section,
        content_type=ContentType.RISK_FACTOR,
        page_start=12,
        page_end=13,
        text=text,
        relevance_score=score,
        retrieval_reason="strong semantic match",
    )


def test_workflow_returns_research_report(mock_llm) -> None:
    retriever = _StubRetriever(
        items=[
            _evidence(CanonicalSection.RISK_FACTORS.value, "Macroeconomic risk and inflation."),
            _evidence(CanonicalSection.RISK_FACTORS.value, "Cybersecurity threats remain."),
            _evidence(CanonicalSection.MDA.value, "Margins compressed due to input costs."),
        ]
    )
    state = run_workflow(
        ResearchQuery(query="What are the key risks for ACME?", ticker="ACME"),
        session=None,
        llm=mock_llm,
        retriever=retriever,
    )
    assert state.final_report is not None
    rep = state.final_report
    assert rep.intent == ResearchIntent.RISK_ANALYSIS
    assert rep.summary
    assert len(rep.evidence) == 3
    # Restricted phrases must not appear in generated content. The
    # canonical disclaimer legitimately mentions "price targets" — strip
    # it from the rendered text before checking.
    md = rep.markdown().lower().replace(rep.no_advice_disclaimer.lower(), "")
    for bad in ("buy this stock", "price target", "should i sell"):
        assert bad not in md


def test_workflow_refuses_advice_questions(mock_llm) -> None:
    state = run_workflow(
        ResearchQuery(query="Should I buy this stock?", ticker="ACME"),
        session=None,
        llm=mock_llm,
        retriever=_StubRetriever(items=[]),
    )
    assert state.refused
    assert state.intent == ResearchIntent.REFUSED_ADVICE
    assert state.final_report is not None
    assert "investment advice" in state.final_report.summary.lower()


def test_streaming_emits_expected_event_types(mock_llm) -> None:
    retriever = _StubRetriever(
        items=[_evidence(CanonicalSection.RISK_FACTORS.value, "macroeconomic risk")]
    )

    async def collect():
        out = []
        async for evt in stream_workflow(
            ResearchQuery(query="What risks does ACME disclose?", ticker="ACME"),
            session=None,
            llm=mock_llm,
            retriever=retriever,
        ):
            out.append(evt.type)
            if len(out) > 200:  # safety cap
                break
        return out

    types = asyncio.run(collect())
    # Compare via either Enum or string form depending on serialization
    types_str = [t.value if hasattr(t, "value") else str(t) for t in types]
    assert EventType.RUN_STARTED.value in types_str
    assert EventType.QUERY_CLASSIFIED.value in types_str
    assert EventType.RETRIEVAL_PLAN.value in types_str
    assert EventType.EVIDENCE_FOUND.value in types_str
    assert EventType.FINAL_REPORT.value in types_str
    assert EventType.RUN_COMPLETED.value in types_str


def test_streaming_payloads_include_full_evidence_and_report(mock_llm) -> None:
    retriever = _StubRetriever(
        items=[_evidence(CanonicalSection.RISK_FACTORS.value, "macroeconomic risk")]
    )

    async def collect():
        out = []
        async for evt in stream_workflow(
            ResearchQuery(
                query="What risks does ACME disclose?",
                ticker="ACME",
                document_ids=[7, 3, 7],
            ),
            session=None,
            llm=mock_llm,
            retriever=retriever,
        ):
            out.append(evt)
        return out

    events = asyncio.run(collect())
    classified = next(evt for evt in events if evt.type == EventType.QUERY_CLASSIFIED)
    assert classified.payload["document_ids"] == [3, 7]

    evidence = next(evt for evt in events if evt.type == EventType.EVIDENCE_FOUND)
    assert evidence.payload["text"] == "macroeconomic risk"
    assert evidence.payload["snippet"] == "macroeconomic risk"
    assert evidence.payload["document_id"] == 1
    assert "score_breakdown" in evidence.payload

    final_report = next(evt for evt in events if evt.type == EventType.FINAL_REPORT)
    assert final_report.payload["summary"]
    assert final_report.payload["evidence"][0]["text"] == "macroeconomic risk"


@pytest.mark.parametrize(
    "query,expected_intent",
    [
        ("What does ACME do?", ResearchIntent.BUSINESS_MODEL),
        ("Why did margins decline?", ResearchIntent.MARGIN_ANALYSIS),
        ("What about liquidity?", ResearchIntent.LIQUIDITY_ANALYSIS),
        ("What were the main revenue drivers?", ResearchIntent.REVENUE_DRIVERS),
        ("Outlook for next year?", ResearchIntent.MANAGEMENT_OUTLOOK),
    ],
)
def test_classifier_routes_intents(query, expected_intent, mock_llm) -> None:
    state = run_workflow(
        ResearchQuery(query=query, ticker="ACME"),
        session=None,
        llm=mock_llm,
        retriever=_StubRetriever(items=[]),
    )
    assert state.intent == expected_intent
