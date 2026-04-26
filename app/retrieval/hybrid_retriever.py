"""Hybrid retriever combining metadata, keyword, and vector signals.

Text relevance is fused via Reciprocal Rank Fusion (Cormack et al. 2009),
which is invariant to the underlying score scales — vector cosine
similarity and ``ts_rank_cd`` aren't directly comparable, so per-result-
set min-max scaling drifted from query to query. RRF only needs the
ranks::

    rrf(rank, k=60) = 1 / (k + rank)
    text_score      = rrf(vector_rank) + rrf(keyword_rank)   # one or both

The text_score is normalized to [0, 1] (max possible is two top-1 hits)
and then combined with the metadata signals::

    score = 0.75 * text
          + 0.10 * section_match
          + 0.10 * source_priority
          + 0.05 * recency

The per-component ``score_breakdown`` is preserved so the UI can still
explain *why* a chunk was retrieved — ``vector`` and ``keyword`` now
report the chunk's RRF contribution from each ranker (0 if absent).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import DocumentChunk
from app.schemas.document import ContentType, DocumentType, SourcePriority
from app.schemas.evidence import EvidenceItem
from app.schemas.graph_state import RetrievalPlan
from app.schemas.query import ResearchQuery

from .keyword_search import KeywordSearch
from .metadata_filter import (
    MetadataFilter,
    content_type_match_score,
    recency_score,
    section_match_score,
    source_priority_score,
)
from .vector_store import VectorStore

if TYPE_CHECKING:
    from app.services.embedding_service import EmbeddingService

log = get_logger(__name__)


RRF_K = 60  # Cormack et al. default — robust across IR benchmarks
_RRF_MAX = 2.0 / (RRF_K + 1)  # both rankers' top hit


@dataclass
class HybridWeights:
    text: float = 0.75  # combined RRF(vector) + RRF(keyword), normalized
    section: float = 0.10
    source: float = 0.10
    recency: float = 0.05


class HybridRetriever:
    def __init__(
        self,
        embedding_service: "EmbeddingService",
        vector_store: VectorStore | None = None,
        keyword_search: KeywordSearch | None = None,
        weights: HybridWeights | None = None,
    ) -> None:
        self.embedding_service = embedding_service
        self.vector_store = vector_store or VectorStore()
        self.keyword_search = keyword_search or KeywordSearch()
        self.w = weights or HybridWeights()

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------
    def retrieve(
        self,
        session: Session,
        query: ResearchQuery,
        plan: RetrievalPlan | None = None,
        k: int | None = None,
    ) -> list[EvidenceItem]:
        top_k = k or (plan.top_k if plan else None) or 12
        filt = MetadataFilter.build(query, plan).to_sqlalchemy()

        # Vector search uses the *expanded* query when the planner provides one
        vec_query_text = (plan.expanded_query if plan and plan.expanded_query else query.query)
        embedding = self.embedding_service.embed_query(vec_query_text)

        vec_hits = self.vector_store.search(session, embedding, where=filt, k=top_k * 4)
        kw_hits = self.keyword_search.search(session, query.query, where=filt, k=top_k * 4)

        # Fallback: if the strict filter wiped out results, retry with
        # ticker-only filter so we never return zero on a real corpus.
        if not vec_hits and not kw_hits:
            log.info("hybrid retriever: strict filter empty — falling back to relaxed")
            relaxed = MetadataFilter.relaxed(query).to_sqlalchemy()
            vec_hits = self.vector_store.search(session, embedding, where=relaxed, k=top_k * 4)
            kw_hits = self.keyword_search.search(session, query.query, where=relaxed, k=top_k * 4)

        return self._fuse(vec_hits, kw_hits, plan, top_k)

    # ------------------------------------------------------------------
    # Score fusion
    # ------------------------------------------------------------------
    def _fuse(
        self,
        vec_hits: list[tuple[DocumentChunk, float]],
        kw_hits: list[tuple[DocumentChunk, float]],
        plan: RetrievalPlan | None,
        top_k: int,
    ) -> list[EvidenceItem]:
        # Rank lookups for RRF — rankers must arrive pre-sorted by their
        # own relevance, which both VectorStore and KeywordSearch do.
        vec_rank = {c.id: i + 1 for i, (c, _) in enumerate(vec_hits)}
        kw_rank = {c.id: i + 1 for i, (c, _) in enumerate(kw_hits)}

        chunk_map: dict[int, DocumentChunk] = {}
        for c, _ in vec_hits:
            chunk_map[c.id] = c
        for c, _ in kw_hits:
            chunk_map.setdefault(c.id, c)

        scored: list[EvidenceItem] = []
        for cid, chunk in chunk_map.items():
            v_rrf = 1.0 / (RRF_K + vec_rank[cid]) if cid in vec_rank else 0.0
            kw_rrf = 1.0 / (RRF_K + kw_rank[cid]) if cid in kw_rank else 0.0
            text_norm = (v_rrf + kw_rrf) / _RRF_MAX

            sec = section_match_score(plan, chunk.section)
            ct = content_type_match_score(plan, chunk.content_type)
            src = source_priority_score(chunk.source_priority)
            rec = recency_score(chunk.fiscal_year)

            # Mix section + content-type bonus into the section signal
            section_signal = max(sec, ct)

            score = (
                self.w.text * text_norm
                + self.w.section * section_signal
                + self.w.source * src
                + self.w.recency * rec
            )

            reason = self._reason(
                vec_rank.get(cid), kw_rank.get(cid), section_signal, src, rec
            )

            scored.append(
                EvidenceItem(
                    source_id=str(chunk.source_id),
                    document_id=chunk.document_id,
                    chunk_index=chunk.chunk_index,
                    ticker=chunk.ticker,
                    company_name=chunk.company_name,
                    document_type=DocumentType(chunk.document_type)
                    if _safe_enum(DocumentType, chunk.document_type)
                    else DocumentType.OTHER,
                    fiscal_year=chunk.fiscal_year,
                    filing_date=chunk.filing_date,
                    source_priority=SourcePriority(chunk.source_priority)
                    if _safe_enum(SourcePriority, chunk.source_priority)
                    else SourcePriority.OTHER,
                    section=chunk.section,
                    subsection=chunk.subsection,
                    content_type=ContentType(chunk.content_type)
                    if _safe_enum(ContentType, chunk.content_type)
                    else ContentType.OTHER,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    text=chunk.chunk_text,
                    metric_tags=list(chunk.metric_tags or []),
                    risk_tags=list(chunk.risk_tags or []),
                    relevance_score=round(score, 4),
                    retrieval_reason=reason,
                    score_breakdown={
                        # Each ranker's normalized RRF contribution (0 if
                        # this chunk wasn't in that ranker's top-k).
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


def _safe_enum(enum_cls, value: str) -> bool:
    try:
        enum_cls(value)
        return True
    except ValueError:
        return False
