"""End-to-end workflow test using fakes.

The retriever is stubbed to return a curated evidence list; the chat
model is :class:`MockChatModel` (deterministic structured output). This
validates that nodes wire up correctly and produce a valid
``ResearchReport``, including the new self-correction loop and the
``evidence_numbers → evidence_ids`` translation step.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda

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

    def retrieve(self, query, plan=None, k=None):  # noqa: D401, ARG002
        return list(self.items)


def _evidence(section: str, text: str, score: float = 0.8, sid: str | None = None) -> EvidenceItem:
    return EvidenceItem(
        source_id=sid or str(uuid.uuid4()),
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


def test_workflow_returns_research_report(mock_chat_model) -> None:
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
        chat_model=mock_chat_model,
        retriever=retriever,
    )
    assert state.final_report is not None
    rep = state.final_report
    assert rep.intent == ResearchIntent.RISK_ANALYSIS
    assert rep.summary
    assert len(rep.evidence) == 3
    md = rep.markdown().lower().replace(rep.no_advice_disclaimer.lower(), "")
    for bad in ("buy this stock", "price target", "should i sell"):
        assert bad not in md


def test_workflow_refuses_advice_questions(mock_chat_model) -> None:
    state = run_workflow(
        ResearchQuery(query="Should I buy this stock?", ticker="ACME"),
        session=None,
        chat_model=mock_chat_model,
        retriever=_StubRetriever(items=[]),
    )
    assert state.refused
    assert state.intent == ResearchIntent.REFUSED_ADVICE
    assert state.final_report is not None
    assert "investment advice" in state.final_report.summary.lower()


def test_streaming_emits_expected_event_types(mock_chat_model) -> None:
    retriever = _StubRetriever(
        items=[_evidence(CanonicalSection.RISK_FACTORS.value, "macroeconomic risk")]
    )

    async def collect():
        out = []
        async for evt in stream_workflow(
            ResearchQuery(query="What risks does ACME disclose?", ticker="ACME"),
            session=None,
            chat_model=mock_chat_model,
            retriever=retriever,
        ):
            out.append(evt.type)
            if len(out) > 200:
                break
        return out

    types = asyncio.run(collect())
    types_str = [t.value if hasattr(t, "value") else str(t) for t in types]
    assert EventType.RUN_STARTED.value in types_str
    assert EventType.QUERY_CLASSIFIED.value in types_str
    assert EventType.RETRIEVAL_PLAN.value in types_str
    assert EventType.EVIDENCE_FOUND.value in types_str
    assert EventType.FINAL_REPORT.value in types_str
    assert EventType.RUN_COMPLETED.value in types_str


def test_streaming_payloads_include_full_evidence_and_report(mock_chat_model) -> None:
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
            chat_model=mock_chat_model,
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
def test_classifier_routes_intents(query, expected_intent, mock_chat_model) -> None:
    state = run_workflow(
        ResearchQuery(query=query, ticker="ACME"),
        session=None,
        chat_model=mock_chat_model,
        retriever=_StubRetriever(items=[]),
    )
    assert state.intent == expected_intent


# ---------------------------------------------------------------------
# Phase 4 — citation translation + self-correction loop
# ---------------------------------------------------------------------
class _ScriptedChatModel(BaseChatModel):
    """Returns a different draft on each ``with_structured_output(...)``
    invocation. Lets us simulate first-draft failures and verify the
    self-correction loop kicks in. Indices saturate at the last draft so
    a runaway loop still returns *something*."""

    # BaseChatModel is a Pydantic model — declare fields as private
    # attrs to escape schema validation.
    from pydantic import PrivateAttr

    _drafts: list[dict] = PrivateAttr(default_factory=list)
    _draft_calls: int = PrivateAttr(default=0)

    def __init__(self, drafts: list[dict]) -> None:
        super().__init__()
        self._drafts = list(drafts)
        self._draft_calls = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-chat"

    def _generate(self, messages, stop=None, run_manager=None, **kw):  # noqa: D401, ARG002
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="unused"))])

    def with_structured_output(self, schema, **_kw) -> Runnable:
        from app.graph.llm_schemas import LLMClassifyOutput, LLMReportDraft

        if schema is LLMClassifyOutput:
            return RunnableLambda(
                lambda _msgs: schema(intent=ResearchIntent.RISK_ANALYSIS, ticker="ACME")
            )
        if schema is LLMReportDraft:
            def _next_draft(_msgs):
                idx = self._draft_calls
                self._draft_calls = idx + 1
                payload = self._drafts[min(idx, len(self._drafts) - 1)]
                return schema(**payload)
            return RunnableLambda(_next_draft)
        return RunnableLambda(lambda _msgs: schema())


def test_self_correction_retries_when_findings_lack_citations() -> None:
    """First draft has uncited findings → validate flips revision_required.
    Second draft cites [1] → workflow accepts and finalizes."""

    drafts = [
        {  # bad first draft — no citations on findings
            "summary": "Initial pass.",
            "key_findings": [
                {"claim": "The company has risks.", "evidence_numbers": []},
            ],
        },
        {  # good retry — cites [1]
            "summary": "Corrected draft.",
            "key_findings": [
                {"claim": "The company faces macroeconomic risk.", "evidence_numbers": [1]},
            ],
        },
    ]
    chat = _ScriptedChatModel(drafts)
    risk = _evidence(CanonicalSection.RISK_FACTORS.value, "Macroeconomic risk discussion.",
                      sid="ev-A")
    state = run_workflow(
        ResearchQuery(query="What risks does ACME face?", ticker="ACME"),
        session=None,
        chat_model=chat,
        retriever=_StubRetriever(items=[risk]),
    )
    assert state.revision_count == 1, "should have retried exactly once"
    assert state.revision_required is False, "loop must terminate after a clean draft"
    assert state.final_report is not None
    finding = state.final_report.key_findings[0]
    assert finding.evidence_ids == ["ev-A"], "evidence_numbers=[1] should map to source_id ev-A"


def test_self_correction_gives_up_after_max_revisions() -> None:
    """Every draft is uncited → workflow eventually stops retrying and
    surfaces the issue as a final-report warning."""
    bad_draft = {
        "summary": "Always uncited.",
        "key_findings": [
            {"claim": "Some claim", "evidence_numbers": []},
        ],
    }
    chat = _ScriptedChatModel([bad_draft, bad_draft, bad_draft, bad_draft])
    risk = _evidence(CanonicalSection.RISK_FACTORS.value, "Risk text.", sid="ev-A")
    state = run_workflow(
        ResearchQuery(query="What risks does ACME face?", ticker="ACME"),
        session=None,
        chat_model=chat,
        retriever=_StubRetriever(items=[risk]),
    )
    assert state.revision_count == 2, "should have retried up to MAX_REVISIONS"
    assert state.revision_required is False
    assert any("without citations" in w for w in state.validation_warnings)
    assert state.final_report is not None  # we still produce a report so the user sees something


def test_citation_numbers_map_to_source_ids() -> None:
    """LLM emits [1, 3] — the workflow must translate them to the matching source_ids."""
    draft = {
        "summary": "Cites first and third evidence.",
        "key_findings": [
            {"claim": "Claim citing two pieces of evidence.", "evidence_numbers": [1, 3]},
        ],
    }
    chat = _ScriptedChatModel([draft])
    items = [
        _evidence(CanonicalSection.RISK_FACTORS.value, "First.",  sid="sid-1"),
        _evidence(CanonicalSection.RISK_FACTORS.value, "Second.", sid="sid-2"),
        _evidence(CanonicalSection.MDA.value,         "Third.",  sid="sid-3"),
    ]
    state = run_workflow(
        ResearchQuery(query="What risks?", ticker="ACME"),
        session=None,
        chat_model=chat,
        retriever=_StubRetriever(items=items),
    )
    # ev numbers are 1-based and dense across all evidence items, so
    # [1, 3] resolves to sid-1 (first chunk) and sid-3 (third chunk).
    finding = state.final_report.key_findings[0]
    assert finding.evidence_ids == ["sid-1", "sid-3"]
