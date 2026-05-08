"""Cross-encoder reranker — second-pass relevance scoring on the
EvidenceItem list produced by :class:`HybridRetriever`.

Why a second pass? The hybrid score blends RRF text relevance with
section / source / recency signals. RRF is rank-based and ignores
fine-grained textual relevance of the chunk to the *exact* query — so
two chunks at similar rank but with very different on-topic density
will tie. A cross-encoder runs the (query, chunk_text) pair through a
single transformer and produces a calibrated relevance score; folding
that into the breakdown promotes the chunks that actually answer the
question.

We layer it INTO the existing breakdown rather than replacing the
score, so UI explanations stay consistent: ``score_breakdown["rerank"]``
appears alongside ``vector`` / ``keyword`` / ``section`` / ``source`` /
``recency``. Disabled by default — flip ``settings.reranker_enabled``
or pass ``enabled=True`` to opt in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.evidence import EvidenceItem

if TYPE_CHECKING:
    from langchain_community.cross_encoders import HuggingFaceCrossEncoder

log = get_logger(__name__)


# Weight on the cross-encoder score in the post-rerank ``relevance_score``.
# The other 0.5 is left to the existing hybrid signal so a strong
# section / source / recency match still matters.
_RERANK_WEIGHT = 0.5


class FilingsReranker:
    """Cross-encoder reranker over a list of :class:`EvidenceItem`.

    Lazy-loads the HuggingFace model so importing this module doesn't
    pull a 500 MB checkpoint until somebody actually reranks.
    """

    def __init__(
        self,
        model_name: str | None = None,
        top_n: int | None = None,
        pool_k: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.model_name = model_name or settings.reranker_model
        self.top_n = top_n or settings.reranker_top_n
        self.pool_k = pool_k or settings.reranker_pool_k
        self.enabled = settings.reranker_enabled if enabled is None else enabled
        self._cross_encoder: HuggingFaceCrossEncoder | None = None

    def _model(self) -> "HuggingFaceCrossEncoder":
        if self._cross_encoder is None:
            from langchain_community.cross_encoders import HuggingFaceCrossEncoder
            log.info("loading cross-encoder", model=self.model_name)
            self._cross_encoder = HuggingFaceCrossEncoder(model_name=self.model_name)
        return self._cross_encoder

    def rerank(
        self,
        query: str,
        items: list[EvidenceItem],
        top_n: int | None = None,
    ) -> list[EvidenceItem]:
        """Reorder ``items`` by cross-encoder relevance + return top ``top_n``.

        - If reranker is disabled or the candidate pool is too small to
          benefit (≤ ``top_n``), returns ``items[:top_n]`` unchanged.
        - On any model failure, logs and falls back to the original order.
        - Mutates the returned items: their ``score_breakdown["rerank"]``
          and ``relevance_score`` reflect the new ranking. Items that
          weren't in the top-``pool_k`` keep their original scores.
        """
        n = top_n or self.top_n
        if not self.enabled or not items:
            return items[:n]
        if len(items) <= n:
            return items[:n]

        pool = items[: self.pool_k]
        try:
            scores = self._model().score(
                [(query, item.text) for item in pool]
            )
        except Exception as e:
            log.warning("rerank failed — keeping hybrid order", err=str(e))
            return items[:self.top_n]

        ce_scores = [_normalize(float(s)) for s in scores]
        for item, ce in zip(pool, ce_scores, strict=True):
            old = item.score_breakdown or {}
            item.score_breakdown = {**old, "rerank": round(ce, 4)}
            blended = (1 - _RERANK_WEIGHT) * item.relevance_score + _RERANK_WEIGHT * ce
            item.relevance_score = round(blended, 4)
            item.retrieval_reason = _augment_reason(item.retrieval_reason, ce)

        pool.sort(key=lambda e: e.relevance_score, reverse=True)
        return pool[:n]


def _normalize(score: float) -> float:
    """BGE rerankers output unbounded logits (~ -10 .. +10). Squash to
    [0, 1] via sigmoid so the score is comparable to other breakdown
    components."""
    import math
    return 1.0 / (1.0 + math.exp(-score))


def _augment_reason(reason: str | None, ce: float) -> str:
    label = "reranked: strong" if ce >= 0.8 else "reranked: ok" if ce >= 0.5 else "reranked: weak"
    if reason:
        return f"{reason}; {label}"
    return label


# Backwards-compat alias — older code imported ``LLMReranker``. The new
# implementation is a cross-encoder, but we keep the name exported so
# downstream imports don't break in this branch.
LLMReranker = FilingsReranker
