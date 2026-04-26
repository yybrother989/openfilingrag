"""LangGraph nodes — pure functions that take a GraphState and return one.

Every node:
  * emits ``node_start`` and ``node_end`` events
  * may emit zero or more ``payload`` events (e.g. ``evidence_found``)
  * never raises — errors are captured into ``state.errors`` and the next
    node decides whether to short-circuit

Nodes accept a :class:`NodeContext` (services bag) so they can be
unit-tested with stubs.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.schemas.evidence import EvidenceItem
from app.schemas.events import EventType
from app.schemas.graph_state import GraphState, RetrievalPlan
from app.schemas.query import ResearchIntent
from app.schemas.report import (
    Confidence,
    Finding,
    FinancialMetric,
    ManagementCommentary,
    Materiality,
    ResearchReport,
    RiskFactor,
)

from .event_emitter import emit
from .policies import (
    REFUSAL_MESSAGE,
    find_restricted_phrases,
    get_policy,
    is_advice_query,
)
from .prompts import (
    CLASSIFY_SYSTEM,
    CLASSIFY_USER_TEMPLATE,
    GENERATE_SYSTEM,
    GENERATE_USER_TEMPLATE,
    VALIDATE_SYSTEM,
    VALIDATE_USER_TEMPLATE,
)

if TYPE_CHECKING:
    from app.retrieval.evidence_store import EvidenceStore
    from app.retrieval.hybrid_retriever import HybridRetriever
    from app.services.llm_service import LLMService

log = get_logger(__name__)


# ---------------------------------------------------------------------
# Service bag passed to every node
# ---------------------------------------------------------------------
@dataclass
class NodeContext:
    session: Session
    llm: "LLMService"
    retriever: "HybridRetriever"
    evidence_store: "EvidenceStore | None" = None
    # Cooperative cancellation: workflow loop checks this between nodes;
    # _wrap also short-circuits if it's set so a node never starts work
    # after the client has gone away.
    cancel_event: threading.Event = field(default_factory=threading.Event)


def make_langgraph_adapter(node_name: str, fn):
    """Wrap a ``(state, ctx)`` node for LangGraph's ``(state, config)`` ABI.

    LangGraph injects a ``RunnableConfig``; we pull the per-run
    :class:`NodeContext` out of ``config["configurable"]["node_context"]``
    so the same node functions are usable both directly (tests) and
    through ``graph.invoke``/``graph.astream``.
    """

    def adapter(state: GraphState, config):
        ctx = config["configurable"]["node_context"]
        return fn(state, ctx)

    adapter.__name__ = node_name
    return adapter


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _wrap(node_name: str):
    """Decorator: emit node_start/node_end and capture exceptions."""

    def decorator(fn):
        def wrapper(state: GraphState, ctx: NodeContext) -> GraphState:
            if ctx.cancel_event.is_set():
                return state
            t0 = time.perf_counter()
            emit(EventType.NODE_START, {"node": node_name}, node=node_name)
            try:
                result = fn(state, ctx)
                emit(
                    EventType.NODE_END,
                    {"node": node_name, "elapsed_ms": int((time.perf_counter() - t0) * 1000)},
                    node=node_name,
                )
                return result
            except Exception as e:
                log.exception("node failed", node=node_name, err=str(e))
                state.errors.append(f"{node_name}: {e}")
                emit(EventType.ERROR, {"node": node_name, "error": str(e)}, node=node_name)
                return state

        wrapper.__name__ = node_name
        return wrapper

    return decorator


# ---------------------------------------------------------------------
# 1. classify_query
# ---------------------------------------------------------------------
@_wrap("classify_query")
def classify_query(state: GraphState, ctx: NodeContext) -> GraphState:
    user_query = state.user_query

    # Pre-query compliance guard — refuse advice questions before we burn
    # any tokens on classification or retrieval.
    if is_advice_query(user_query.query):
        state.intent = ResearchIntent.REFUSED_ADVICE
        state.refused = True
        state.validation_warnings.append(REFUSAL_MESSAGE)
        emit(
            EventType.QUERY_CLASSIFIED,
            {
                "intent": ResearchIntent.REFUSED_ADVICE.value,
                "refused": True,
                "reason": "advice question",
                "message": REFUSAL_MESSAGE,
            },
            node="classify_query",
        )
        return state

    payload = ctx.llm.chat_json(
        system=CLASSIFY_SYSTEM,
        user=CLASSIFY_USER_TEMPLATE.format(
            query=user_query.query,
            ticker=user_query.ticker or "null",
            company_name=user_query.company_name or "null",
            fiscal_year=user_query.fiscal_year or "null",
        ),
    )

    try:
        intent = ResearchIntent(payload.get("intent") or ResearchIntent.GENERIC_FILING_QA.value)
    except ValueError:
        intent = ResearchIntent.GENERIC_FILING_QA

    state.intent = intent
    state.ticker = (payload.get("ticker") or user_query.ticker or "").upper() or None
    state.company_name = payload.get("company_name") or user_query.company_name
    if user_query.fiscal_year:
        fiscal_year = user_query.fiscal_year
    else:
        fy = payload.get("fiscal_year")
        fiscal_year = int(fy) if isinstance(fy, (int, str)) and str(fy).isdigit() else None
    state.filters["fiscal_year"] = fiscal_year
    state.filters["wants_cross_year"] = bool(payload.get("wants_cross_year"))

    emit(
        EventType.QUERY_CLASSIFIED,
        {
            "intent": intent.value,
            "ticker": state.ticker,
            "company_name": state.company_name,
            "fiscal_year": fiscal_year,
            "document_ids": list(user_query.document_ids),
            "wants_cross_year": state.filters["wants_cross_year"],
        },
        node="classify_query",
    )
    return state


# ---------------------------------------------------------------------
# 2. plan_retrieval
# ---------------------------------------------------------------------
@_wrap("plan_retrieval")
def plan_retrieval(state: GraphState, ctx: NodeContext) -> GraphState:
    if state.refused:
        return state

    intent = state.intent or ResearchIntent.GENERIC_FILING_QA
    policy = get_policy(intent)

    # Apply user filter overrides
    top_k = state.user_query.top_k or policy.top_k

    expanded = state.user_query.query
    if policy.metric_expansions:
        expanded += " " + " ".join(policy.metric_expansions)
    if policy.risk_expansions:
        expanded += " " + " ".join(policy.risk_expansions)

    plan = RetrievalPlan(
        intent=intent,
        preferred_sections=policy.preferred_sections,
        preferred_document_types=policy.preferred_document_types,
        preferred_content_types=policy.preferred_content_types,
        metric_expansions=policy.metric_expansions,
        risk_expansions=policy.risk_expansions,
        cross_year=policy.cross_year or state.filters.get("wants_cross_year", False),
        table_priority=policy.table_priority,
        top_k=top_k,
        expanded_query=expanded,
    )
    state.retrieval_plan = plan

    emit(
        EventType.RETRIEVAL_PLAN,
        {
            "intent": intent.value,
            "document_ids": list(state.user_query.document_ids),
            "preferred_sections": plan.preferred_sections,
            "preferred_document_types": plan.preferred_document_types,
            "preferred_content_types": plan.preferred_content_types,
            "metric_expansions": plan.metric_expansions,
            "risk_expansions": plan.risk_expansions,
            "cross_year": plan.cross_year,
            "table_priority": plan.table_priority,
            "top_k": plan.top_k,
        },
        node="plan_retrieval",
    )
    if plan.preferred_sections:
        emit(
            EventType.SECTION_SELECTED,
            {"sections": plan.preferred_sections},
            node="plan_retrieval",
        )
    return state


# ---------------------------------------------------------------------
# 3. retrieve_evidence
# ---------------------------------------------------------------------
@_wrap("retrieve_evidence")
def retrieve_evidence(state: GraphState, ctx: NodeContext) -> GraphState:
    if state.refused:
        return state
    plan = state.retrieval_plan
    items = ctx.retriever.retrieve(state.user_query, plan)
    state.evidence_items = items

    for item in items:
        payload = item.model_dump(mode="json")
        payload["snippet"] = item.text[:280]
        emit(
            EventType.EVIDENCE_FOUND,
            payload,
            node="retrieve_evidence",
        )
    return state


# ---------------------------------------------------------------------
# 4. verify_evidence
# ---------------------------------------------------------------------
@_wrap("verify_evidence")
def verify_evidence(state: GraphState, ctx: NodeContext) -> GraphState:
    if state.refused:
        return state

    items = state.evidence_items
    # Deduplicate by source_id keeping the highest-scored
    by_id: dict[str, EvidenceItem] = {}
    for it in items:
        existing = by_id.get(it.source_id)
        if not existing or it.relevance_score > existing.relevance_score:
            by_id[it.source_id] = it

    deduped = sorted(by_id.values(), key=lambda e: e.relevance_score, reverse=True)

    # Drop very weak candidates
    from app.core.config import settings

    filtered = [e for e in deduped if e.relevance_score >= settings.min_evidence_score]

    if not filtered:
        msg = "No evidence chunks passed the minimum relevance threshold."
        state.validation_warnings.append(msg)
        emit(
            EventType.VERIFICATION_WARNING,
            {"warning": msg, "candidates_seen": len(items)},
            node="verify_evidence",
        )
    elif len(filtered) < 3:
        msg = f"Only {len(filtered)} evidence item(s) found — answer may be thin."
        state.validation_warnings.append(msg)
        emit(EventType.VERIFICATION_WARNING, {"warning": msg}, node="verify_evidence")

    state.evidence_items = filtered
    return state


# ---------------------------------------------------------------------
# 5. generate_report
# ---------------------------------------------------------------------
@_wrap("generate_report")
def generate_report(state: GraphState, ctx: NodeContext) -> GraphState:
    if state.refused:
        state.final_report = _refusal_report(state)
        emit(EventType.FINAL_REPORT, {"refused": True}, node="generate_report")
        return state

    evidence_block = _format_evidence_for_prompt(state.evidence_items)

    payload = ctx.llm.chat_json(
        system=GENERATE_SYSTEM,
        user=GENERATE_USER_TEMPLATE.format(
            query=state.user_query.query,
            intent=(state.intent or ResearchIntent.GENERIC_FILING_QA).value,
            ticker=state.ticker or "n/a",
            company=state.company_name or "n/a",
            evidence_block=evidence_block,
        ),
    )

    report = _payload_to_report(payload, state)
    state.draft_report = report

    # Emit per-section markers so the UI can render incrementally
    for sect_name in ("summary", "key_findings", "financial_metrics", "risk_factors", "management_commentary"):
        emit(
            EventType.REPORT_SECTION,
            {"section": sect_name},
            node="generate_report",
        )
    return state


# ---------------------------------------------------------------------
# 6. validate_report
# ---------------------------------------------------------------------
@_wrap("validate_report")
def validate_report(state: GraphState, ctx: NodeContext) -> GraphState:
    if state.refused:
        return state

    draft = state.draft_report
    if draft is None:
        msg = "no draft report to validate"
        state.errors.append(msg)
        emit(EventType.ERROR, {"error": msg}, node="validate_report")
        return state

    warnings: list[str] = []
    available_ids = {e.source_id for e in state.evidence_items}

    # 1. Compliance regex check on rendered text
    rendered = draft.markdown()
    matches = find_restricted_phrases(rendered)
    if matches:
        warnings.append(
            "Restricted phrases detected: " + ", ".join(sorted(set(matches)))
        )

    # 2. Citation check — every Finding must cite at least one valid evidence_id
    uncited = [f.claim[:80] for f in draft.key_findings if not f.evidence_ids]
    if uncited:
        warnings.append(
            f"{len(uncited)} finding(s) lack citations: {uncited[:3]}"
        )
    bogus = [
        eid for f in draft.key_findings for eid in f.evidence_ids if eid not in available_ids
    ]
    if bogus:
        warnings.append(
            f"{len(bogus)} finding citation(s) reference unknown evidence_ids"
        )

    for w in warnings:
        emit(EventType.VERIFICATION_WARNING, {"warning": w}, node="validate_report")

    state.validation_warnings.extend(warnings)
    state.final_report = draft
    return state


# ---------------------------------------------------------------------
# 7. format_output
# ---------------------------------------------------------------------
@_wrap("format_output")
def format_output(state: GraphState, ctx: NodeContext) -> GraphState:
    if state.refused:
        emit(
            EventType.FINAL_REPORT,
            {"refused": True, "message": REFUSAL_MESSAGE},
            node="format_output",
        )
        return state

    final = state.final_report
    if not final:
        return state

    # Attach validation warnings + evidence into the final report
    final.validation_warnings = list(state.validation_warnings)
    final.evidence = state.evidence_items
    state.final_report = final

    # Persist the report row first (evidence_items.report_id has an FK
    # to research_reports.report_id, so saving evidence before the parent
    # row would violate the constraint and leave the session in a
    # rolled-back state — which then crashes the SSE stream's outer
    # commit with PendingRollbackError).
    if ctx.evidence_store is not None:
        try:
            _persist_report_row(ctx.session, final)
            ctx.evidence_store.save_for_report(
                ctx.session, final.report_id, state.evidence_items
            )
            ctx.session.commit()
        except Exception as e:
            log.warning("evidence persist failed", err=str(e))
            # Roll back to clear the failed transaction so subsequent
            # commits (e.g. session_scope's exit) don't bomb.
            try:
                ctx.session.rollback()
            except Exception:
                pass

    emit(
        EventType.FINAL_REPORT,
        final.model_dump(mode="json"),
        node="format_output",
    )
    return state


# ---------------------------------------------------------------------
# Helpers — payload conversion & refusal report
# ---------------------------------------------------------------------
def _persist_report_row(session: Session, final: ResearchReport) -> None:
    """Insert the final report into research_reports if not already there.

    Idempotent on report_id (the column has a unique index, but our
    workflow only generates a fresh UUID per run so collisions don't
    happen in practice — this defensive check just keeps things safe
    if the same workflow is ever re-driven through a checkpoint).
    """
    from app.db.models import ResearchReportRow

    try:
        rid = uuid.UUID(final.report_id)
    except (ValueError, TypeError):
        return
    existing = session.scalar(
        ResearchReportRow.__table__.select().where(ResearchReportRow.report_id == rid)
    )
    if existing:
        return
    session.add(
        ResearchReportRow(
            report_id=rid,
            query=final.query,
            ticker=final.ticker,
            company_name=final.company_name,
            intent=final.intent.value if final.intent else None,
            payload=final.model_dump(mode="json"),
        )
    )
    session.flush()


def _format_evidence_for_prompt(items: list[EvidenceItem]) -> str:
    if not items:
        return "(no evidence retrieved)"
    parts = []
    for e in items:
        parts.append(
            f"[id={e.source_id} | section={e.section} | page={e.page_start}-{e.page_end}]\n"
            f"{e.text[:1200]}"
        )
    return "\n\n---\n\n".join(parts)


def _payload_to_report(payload: dict, state: GraphState) -> ResearchReport:
    try:
        findings = [
            Finding(
                claim=f.get("claim", ""),
                evidence_ids=list(f.get("evidence_ids") or []),
                confidence=Confidence(f.get("confidence", "medium")),
                reasoning_summary=f.get("reasoning_summary"),
            )
            for f in payload.get("key_findings", []) or []
            if f.get("claim")
        ]
    except (ValueError, TypeError):
        findings = []

    try:
        metrics = [
            FinancialMetric(
                metric_name=m.get("metric_name", ""),
                period=m.get("period"),
                value=str(m.get("value")) if m.get("value") is not None else None,
                change=str(m.get("change")) if m.get("change") is not None else None,
                source_evidence_ids=list(m.get("source_evidence_ids") or []),
            )
            for m in payload.get("financial_metrics", []) or []
            if m.get("metric_name")
        ]
    except (ValueError, TypeError):
        metrics = []

    try:
        risks = [
            RiskFactor(
                risk=r.get("risk", ""),
                category=r.get("category"),
                materiality=Materiality(r.get("materiality", "unknown")),
                evidence_ids=list(r.get("evidence_ids") or []),
            )
            for r in payload.get("risk_factors", []) or []
            if r.get("risk")
        ]
    except (ValueError, TypeError):
        risks = []

    commentary = [
        ManagementCommentary(
            topic=c.get("topic", ""),
            quote_or_paraphrase=c.get("quote_or_paraphrase", ""),
            evidence_ids=list(c.get("evidence_ids") or []),
        )
        for c in payload.get("management_commentary", []) or []
        if c.get("topic")
    ]

    intent = state.intent or ResearchIntent.GENERIC_FILING_QA
    return ResearchReport(
        report_id=str(uuid.uuid4()),
        query=state.user_query.query,
        ticker=state.ticker,
        company_name=state.company_name,
        intent=intent,
        summary=payload.get("summary", "").strip()
        or "Mock summary: the system retrieved evidence and generated a structured outline.",
        key_findings=findings,
        financial_metrics=metrics,
        risk_factors=risks,
        management_commentary=commentary,
        evidence=state.evidence_items,
        limitations=list(payload.get("limitations") or []),
    )


def _refusal_report(state: GraphState) -> ResearchReport:
    return ResearchReport(
        report_id=str(uuid.uuid4()),
        query=state.user_query.query,
        ticker=state.ticker or state.user_query.ticker,
        company_name=state.company_name or state.user_query.company_name,
        intent=ResearchIntent.REFUSED_ADVICE,
        summary=REFUSAL_MESSAGE,
        key_findings=[],
        evidence=[],
        limitations=[
            "Investment-advice request refused under prototype compliance policy.",
        ],
    )
