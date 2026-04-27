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

import time
import uuid
from dataclasses import dataclass
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

from .citations import build_citation_corpus, numbers_to_source_ids
from .llm_schemas import (
    LLMClassifyOutput,
    LLMReportDraft,
)
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
    REVISION_FEEDBACK_TEMPLATE,
)
from .streaming import emit

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from app.retrieval.evidence_store import EvidenceStore
    from app.retrieval.hybrid_retriever import HybridRetriever

log = get_logger(__name__)


# Hard upper bound on validate → generate retries. LangGraph default
# recursion_limit is 25, which is far above this.
MAX_REVISIONS = 2


# ---------------------------------------------------------------------
# Service bag passed to every node
# ---------------------------------------------------------------------
@dataclass
class NodeContext:
    session: Session
    chat_model: "BaseChatModel"
    retriever: "HybridRetriever"
    evidence_store: "EvidenceStore | None" = None


def make_langgraph_adapter(node_name: str, fn):
    """Wrap a ``(state, ctx)`` node for LangGraph's ``(state, config)`` ABI."""

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

    # Pre-query compliance guard — refuse advice questions before we
    # burn any tokens on classification or retrieval.
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

    structured = ctx.chat_model.with_structured_output(LLMClassifyOutput)
    out: LLMClassifyOutput = structured.invoke(
        [
            {"role": "system", "content": CLASSIFY_SYSTEM},
            {
                "role": "user",
                "content": CLASSIFY_USER_TEMPLATE.format(
                    query=user_query.query,
                    ticker=user_query.ticker or "null",
                    company_name=user_query.company_name or "null",
                    fiscal_year=user_query.fiscal_year or "null",
                ),
            },
        ]
    )

    state.intent = out.intent
    state.ticker = (out.ticker or user_query.ticker or "").upper() or None
    state.company_name = out.company_name or user_query.company_name
    fiscal_year = user_query.fiscal_year or out.fiscal_year
    state.filters["fiscal_year"] = fiscal_year
    state.filters["wants_cross_year"] = bool(out.wants_cross_year)

    emit(
        EventType.QUERY_CLASSIFIED,
        {
            "intent": out.intent.value,
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
    by_id: dict[str, EvidenceItem] = {}
    for it in items:
        existing = by_id.get(it.source_id)
        if not existing or it.relevance_score > existing.relevance_score:
            by_id[it.source_id] = it

    deduped = sorted(by_id.values(), key=lambda e: e.relevance_score, reverse=True)

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
        state.draft_report = _refusal_report(state)
        emit(EventType.FINAL_REPORT, {"refused": True}, node="generate_report")
        return state

    # GROUNDING: LLM input is exactly (user query, evidence-derived
    # citation chunks). No external context is supplied.
    citation_text, num_map = build_citation_corpus(state.evidence_items)

    user_prompt = GENERATE_USER_TEMPLATE.format(
        query=state.user_query.query,
        intent=(state.intent or ResearchIntent.GENERIC_FILING_QA).value,
        ticker=state.ticker or "n/a",
        company=state.company_name or "n/a",
        evidence_block=citation_text,
    )

    if state.last_validation_issues:
        feedback = REVISION_FEEDBACK_TEMPLATE.format(
            issues="\n".join(f"- {x}" for x in state.last_validation_issues)
        )
        user_prompt += "\n\n" + feedback

    structured = ctx.chat_model.with_structured_output(LLMReportDraft)
    draft = structured.invoke(
        [
            {"role": "system", "content": GENERATE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
    )

    state.draft_report = _build_research_report(draft, state, num_map)
    # Feedback was consumed by the LLM in this iteration — clear so
    # validate can decide afresh whether another retry is needed.
    state.last_validation_issues = []

    for sect_name in (
        "summary",
        "key_findings",
        "financial_metrics",
        "risk_factors",
        "management_commentary",
    ):
        emit(
            EventType.REPORT_SECTION,
            {"section": sect_name, "revision": state.revision_count},
            node="generate_report",
        )
    return state


# ---------------------------------------------------------------------
# 6. validate_report — also drives the self-correction loop
# ---------------------------------------------------------------------
@_wrap("validate_report")
def validate_report(state: GraphState, ctx: NodeContext) -> GraphState:
    if state.refused:
        state.revision_required = False
        # Refusal flow has the canned report on draft; promote so
        # format_output / API can return it.
        if state.final_report is None and state.draft_report is not None:
            state.final_report = state.draft_report
        return state

    draft = state.draft_report
    if draft is None:
        msg = "no draft report to validate"
        state.errors.append(msg)
        state.revision_required = False
        emit(EventType.ERROR, {"error": msg}, node="validate_report")
        return state

    issues: list[str] = []
    available_ids = {e.source_id for e in state.evidence_items}

    # 1. Compliance regex on rendered text
    matches = find_restricted_phrases(draft.markdown())
    if matches:
        issues.append("Restricted phrases: " + ", ".join(sorted(set(matches))))

    # 2. Grounding: every Finding must cite at least one evidence_id
    uncited = [f.claim[:80] for f in draft.key_findings if not f.evidence_ids]
    if uncited:
        issues.append(f"{len(uncited)} finding(s) without citations: {uncited[:3]}")

    # 3. Grounding: citations must resolve to actually-retrieved evidence
    bogus = [
        eid
        for f in draft.key_findings
        for eid in f.evidence_ids
        if eid not in available_ids
    ]
    if bogus:
        issues.append(f"{len(bogus)} citation(s) reference unknown source_ids")

    # Self-correction: route back to generate_report with feedback.
    if issues and state.revision_count < MAX_REVISIONS:
        state.revision_count += 1
        state.revision_required = True
        state.last_validation_issues = issues
        for w in issues:
            emit(
                EventType.VERIFICATION_WARNING,
                {"warning": w, "revision": state.revision_count},
                node="validate_report",
            )
        return state

    # Either issue-free or hit retry cap — accept the draft. Surface any
    # remaining issues as validation_warnings on the final report.
    state.revision_required = False
    if issues:
        state.validation_warnings.extend(issues)
        for w in issues:
            emit(
                EventType.VERIFICATION_WARNING,
                {"warning": w, "final": True},
                node="validate_report",
            )
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

    final.validation_warnings = list(state.validation_warnings)
    final.evidence = state.evidence_items
    state.final_report = final

    if ctx.evidence_store is not None:
        try:
            _persist_report_row(ctx.session, final)
            ctx.evidence_store.save_for_report(
                ctx.session, final.report_id, state.evidence_items
            )
            ctx.session.commit()
        except Exception as e:
            log.warning("evidence persist failed", err=str(e))
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


def _build_research_report(
    draft: LLMReportDraft,
    state: GraphState,
    num_map: dict[int, str],
) -> ResearchReport:
    """Translate the LLM-facing ``LLMReportDraft`` into the public
    :class:`ResearchReport`, mapping every ``evidence_numbers`` to
    project ``source_id`` strings."""

    findings = [
        Finding(
            claim=f.claim,
            evidence_ids=numbers_to_source_ids(f.evidence_numbers, num_map),
            confidence=f.confidence or Confidence.MEDIUM,
            reasoning_summary=f.reasoning_summary,
        )
        for f in draft.key_findings
        if f.claim
    ]

    metrics = [
        FinancialMetric(
            metric_name=m.metric_name,
            period=m.period,
            value=m.value,
            change=m.change,
            source_evidence_ids=numbers_to_source_ids(m.evidence_numbers, num_map),
        )
        for m in draft.financial_metrics
        if m.metric_name
    ]

    risks = [
        RiskFactor(
            risk=r.risk,
            category=r.category,
            materiality=r.materiality or Materiality.UNKNOWN,
            evidence_ids=numbers_to_source_ids(r.evidence_numbers, num_map),
        )
        for r in draft.risk_factors
        if r.risk
    ]

    commentary = [
        ManagementCommentary(
            topic=c.topic,
            quote_or_paraphrase=c.quote_or_paraphrase,
            evidence_ids=numbers_to_source_ids(c.evidence_numbers, num_map),
        )
        for c in draft.management_commentary
        if c.topic
    ]

    intent = state.intent or ResearchIntent.GENERIC_FILING_QA
    return ResearchReport(
        report_id=str(uuid.uuid4()),
        query=state.user_query.query,
        ticker=state.ticker,
        company_name=state.company_name,
        intent=intent,
        summary=(draft.summary or "").strip()
        or "The retrieved evidence did not contain enough information to answer the question.",
        key_findings=findings,
        financial_metrics=metrics,
        risk_factors=risks,
        management_commentary=commentary,
        evidence=state.evidence_items,
        limitations=list(draft.limitations or []),
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
