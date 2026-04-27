"""Hybrid retriever combining PGVector + Postgres FTS via Reciprocal
Rank Fusion (Cormack et al. 2009).

Vector cosine similarity and ``ts_rank_cd`` aren't directly comparable,
so we fuse on **rank** rather than raw scores::

    rrf(rank, k=60) = 1 / (k + rank)
    text_score      = rrf(vector_rank) + rrf(keyword_rank)   # normalized

Final score adds metadata signals layered onto the text score::

    score = 0.75 * text
          + 0.10 * section_match (or content_type bonus, whichever higher)
          + 0.10 * source_priority
          + 0.05 * recency

The per-component breakdown is preserved in ``EvidenceItem.score_breakdown``
for UI explainability ("strong semantic match; preferred section…").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_cls
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from langchain_core.documents import Document

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.document import ContentType, DocumentType, SourcePriority
from app.schemas.evidence import EvidenceItem
from app.schemas.graph_state import RetrievalPlan
from app.schemas.query import ResearchQuery

from .metadata_filter import (
    MetadataFilter,
    content_type_match_score,
    recency_score,
    section_match_score,
    source_priority_score,
)
from .pg_fts_retriever import PGFTSRetriever
from .pg_vector_store import build_pg_vector
from .reranker import FilingsReranker

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings
    from langchain_postgres import PGVector

log = get_logger(__name__)


RRF_K = 60  # Cormack et al. default — robust across IR benchmarks
_RRF_MAX = 2.0 / (RRF_K + 1)  # both rankers' top hit


@dataclass
class HybridWeights:
    text: float = 0.75
    section: float = 0.10
    source: float = 0.10
    recency: float = 0.05


class HybridRetriever:
    """PGVector + PGFTSRetriever, fused with RRF + metadata weights."""

    def __init__(
        self,
        embeddings: "Embeddings",
        vector_store: "PGVector | None" = None,
        fts_retriever: PGFTSRetriever | None = None,
        weights: HybridWeights | None = None,
        reranker: FilingsReranker | None = None,
    ) -> None:
        self.embeddings = embeddings
        self._vector_store = vector_store
        self._fts_retriever = fts_retriever
        self.w = weights or HybridWeights()
        self.reranker = reranker or FilingsReranker()

    # -- lazy backends ---------------------------------------------------
    @property
    def vector_store(self) -> "PGVector":
        if self._vector_store is None:
            self._vector_store = build_pg_vector(self.embeddings)
        return self._vector_store

    def _build_fts(self, *, k: int, filt: dict[str, Any] | None) -> PGFTSRetriever:
        if self._fts_retriever is not None:
            # Test injection: caller controls k/filter via the stub itself.
            return self._fts_retriever
        # Reuse PGVector's underlying engine if available (avoids opening
        # a second pool); fall back to a fresh engine from settings.
        engine = getattr(self.vector_store, "_async_engine", None) or getattr(
            self.vector_store, "_engine", None
        )
        if engine is None or isinstance(engine, sa.ext.asyncio.AsyncEngine):
            engine = sa.create_engine(settings.database_url, pool_pre_ping=True)
        # Scope to this PGVector's collection so cross-project tables stay isolated.
        collection_id = self._collection_id()
        return PGFTSRetriever(
            engine=engine,
            collection_id=collection_id,
            k=k,
            filter=filt,
        )

    def _collection_id(self) -> Any | None:
        """Return the UUID of the PGVector collection if it has been
        created. Returns ``None`` if the collection lookup fails (e.g.
        before any docs have been indexed)."""
        try:
            collection = self.vector_store.get_collection(
                self.vector_store.session_maker()
            )
            return collection.uuid if collection else None
        except Exception:
            return None

    # -- main API --------------------------------------------------------
    def retrieve(
        self,
        query: ResearchQuery,
        plan: RetrievalPlan | None = None,
        k: int | None = None,
    ) -> list[EvidenceItem]:
        top_k = k or (plan.top_k if plan else None) or 12
        filt = MetadataFilter.build(query, plan).to_pgvector_filter()

        vec_query_text = (plan.expanded_query if plan and plan.expanded_query else query.query)
        vec_docs = self.vector_store.similarity_search(
            vec_query_text, k=top_k * 4, filter=filt
        )
        kw_docs = self._build_fts(k=top_k * 4, filt=filt).invoke(query.query)

        if not vec_docs and not kw_docs:
            log.info("hybrid retriever: strict filter empty — falling back to relaxed")
            relaxed = MetadataFilter.relaxed(query).to_pgvector_filter()
            vec_docs = self.vector_store.similarity_search(
                vec_query_text, k=top_k * 4, filter=relaxed
            )
            kw_docs = self._build_fts(k=top_k * 4, filt=relaxed).invoke(query.query)

        # When the reranker is enabled we surface a larger pool from
        # fusion so the cross-encoder has more candidates to reorder.
        # With reranker disabled this collapses to the previous flow.
        pool_size = max(top_k, self.reranker.pool_k) if self.reranker.enabled else top_k
        fused = self._fuse(vec_docs, kw_docs, plan, pool_size)
        if not self.reranker.enabled:
            return fused[:top_k]
        return self.reranker.rerank(query.query, fused, top_n=top_k)

    # -- fusion ----------------------------------------------------------
    def _fuse(
        self,
        vec_docs: list[Document],
        kw_docs: list[Document],
        plan: RetrievalPlan | None,
        top_k: int,
    ) -> list[EvidenceItem]:
        # Use source_id (the project-stable UUID we wrote into metadata)
        # as the merge key. Falls back to LangChain doc id if missing.
        vec_rank = {self._key(d): i + 1 for i, d in enumerate(vec_docs)}
        kw_rank = {self._key(d): i + 1 for i, d in enumerate(kw_docs)}

        doc_map: dict[str, Document] = {}
        for d in vec_docs:
            doc_map[self._key(d)] = d
        for d in kw_docs:
            doc_map.setdefault(self._key(d), d)

        scored: list[EvidenceItem] = []
        for key, doc in doc_map.items():
            v_rrf = 1.0 / (RRF_K + vec_rank[key]) if key in vec_rank else 0.0
            kw_rrf = 1.0 / (RRF_K + kw_rank[key]) if key in kw_rank else 0.0
            text_norm = (v_rrf + kw_rrf) / _RRF_MAX

            md = doc.metadata or {}
            section = md.get("section", "") or ""
            content_type = md.get("content_type", "paragraph") or "paragraph"
            sec = section_match_score(plan, section)
            ct = content_type_match_score(plan, content_type)
            section_signal = max(sec, ct)
            src = source_priority_score(md.get("source_priority", "primary_filing") or "primary_filing")
            rec = recency_score(md.get("fiscal_year"))

            score = (
                self.w.text * text_norm
                + self.w.section * section_signal
                + self.w.source * src
                + self.w.recency * rec
            )

            reason = self._reason(
                vec_rank.get(key), kw_rank.get(key), section_signal, src, rec
            )

            scored.append(
                _document_to_evidence(
                    doc=doc,
                    score=score,
                    reason=reason,
                    breakdown={
                        "vector": round(v_rrf / _RRF_MAX, 4),
                        "keyword": round(kw_rrf / _RRF_MAX, 4),
                        "section": round(section_signal, 4),
                        "source": round(src, 4),
                        "recency": round(rec, 4),
                    },
                )
            )

        scored.sort(key=lambda e: e.relevance_score, reverse=True)
        return scored[:top_k]

    @staticmethod
    def _key(doc: Document) -> str:
        md = doc.metadata or {}
        return str(md.get("source_id") or doc.id or id(doc))

    @staticmethod
    def _reason(
        v_rank: int | None,
        kw_rank: int | None,
        sec: float,
        src: float,
        rec: float,
    ) -> str:
        parts: list[str] = []
        if v_rank is not None and v_rank <= 5:
            parts.append("strong semantic match")
        elif v_rank is not None and v_rank <= 20:
            parts.append("moderate semantic match")
        if kw_rank is not None and kw_rank <= 10:
            parts.append("keyword hit")
        if sec >= 0.5:
            parts.append("preferred section")
        if src >= 0.9:
            parts.append("primary filing")
        if rec >= 0.8:
            parts.append("recent filing")
        if not parts:
            parts.append("baseline match")
        return "; ".join(parts)


# ----------------------------------------------------------------------
# Document → EvidenceItem
# ----------------------------------------------------------------------
def _document_to_evidence(
    doc: Document,
    *,
    score: float,
    reason: str,
    breakdown: dict[str, float],
) -> EvidenceItem:
    md = doc.metadata or {}

    return EvidenceItem(
        source_id=str(md.get("source_id") or uuid.uuid4()),
        document_id=int(md.get("document_id") or 0),
        chunk_index=int(md.get("chunk_index") or 0),
        ticker=str(md.get("ticker") or ""),
        company_name=md.get("company_name"),
        document_type=_safe_enum(DocumentType, md.get("document_type"), DocumentType.OTHER),
        fiscal_year=md.get("fiscal_year"),
        filing_date=_parse_date(md.get("filing_date")),
        source_priority=_safe_enum(
            SourcePriority, md.get("source_priority"), SourcePriority.PRIMARY_FILING
        ),
        section=str(md.get("section") or ""),
        subsection=md.get("subsection"),
        content_type=_safe_enum(ContentType, md.get("content_type"), ContentType.PARAGRAPH),
        page_start=md.get("page_start"),
        page_end=md.get("page_end"),
        text=doc.page_content or "",
        metric_tags=list(md.get("metric_tags") or []),
        risk_tags=list(md.get("risk_tags") or []),
        relevance_score=round(score, 4),
        retrieval_reason=reason,
        score_breakdown=breakdown,
    )


def _safe_enum(enum_cls, value, default):
    try:
        return enum_cls(value) if value is not None else default
    except ValueError:
        return default


def _parse_date(value: Any) -> date_cls | None:
    if value is None:
        return None
    if isinstance(value, date_cls):
        return value
    try:
        return date_cls.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
