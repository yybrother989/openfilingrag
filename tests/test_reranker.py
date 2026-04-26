"""FilingsReranker — fast / behaviour-only checks.

We don't load the production cross-encoder here (BAAI/bge-reranker-v2-m3
is ~1.5 GB). The disabled / short-pool / no-op paths are exercised
without any model. The smoke test that actually loads a tiny model is
guarded by a marker so default ``pytest`` runs stay offline.
"""

from __future__ import annotations

import uuid

import pytest

from app.retrieval.reranker import FilingsReranker
from app.schemas.document import (
    ContentType,
    DocumentType,
    SourcePriority,
)
from app.schemas.evidence import EvidenceItem


def _ev(text: str, score: float = 0.5) -> EvidenceItem:
    return EvidenceItem(
        source_id=str(uuid.uuid4()),
        document_id=1,
        ticker="ACME",
        document_type=DocumentType.TEN_K,
        source_priority=SourcePriority.PRIMARY_FILING,
        section="Risk Factors",
        content_type=ContentType.RISK_FACTOR,
        text=text,
        relevance_score=score,
        score_breakdown={"vector": score, "keyword": 0.0,
                          "section": 1.0, "source": 1.0, "recency": 0.9},
    )


def test_disabled_passes_through() -> None:
    r = FilingsReranker(enabled=False, top_n=3)
    items = [_ev(f"chunk {i}", 0.9 - 0.1 * i) for i in range(5)]
    out = r.rerank("anything", items)
    # Same order, trimmed to top_n
    assert [i.text for i in out] == ["chunk 0", "chunk 1", "chunk 2"]


def test_skips_when_pool_smaller_than_top_n() -> None:
    """No point reranking 3 candidates when caller wants top-3."""
    r = FilingsReranker(enabled=True, top_n=3)
    items = [_ev(f"chunk {i}", 0.5) for i in range(3)]
    out = r.rerank("query", items)
    # Returns original list unchanged (no model loaded)
    assert [i.text for i in out] == ["chunk 0", "chunk 1", "chunk 2"]
    # And doesn't add a "rerank" key to score_breakdown
    assert all("rerank" not in (i.score_breakdown or {}) for i in out)


def test_top_n_override() -> None:
    r = FilingsReranker(enabled=False, top_n=10)
    items = [_ev(f"c{i}", 0.5) for i in range(5)]
    out = r.rerank("q", items, top_n=2)
    assert len(out) == 2


@pytest.mark.integration
def test_real_cross_encoder_promotes_relevant_chunk() -> None:
    """Smoke: a tiny cross-encoder should rank the on-topic chunk first.

    Skipped by default — run with ``pytest -m integration``. Downloads
    a ~20 MB model on first run and caches it under ~/.cache.
    """
    r = FilingsReranker(
        model_name="cross-encoder/ms-marco-TinyBERT-L-2-v2",
        enabled=True,
        top_n=2,
        pool_k=10,
    )
    items = [
        _ev("Apple reported strong iPhone sales growth in Q4 2024.", 0.5),
        _ev("Cybersecurity threats from nation-state actors continue.", 0.5),
        _ev("The board declared a quarterly dividend of $0.25 per share.", 0.5),
        _ev("Foreign currency fluctuations could impact revenue.", 0.5),
    ]
    out = r.rerank("How much did iPhone sales grow?", items)
    assert "iPhone" in out[0].text
    assert out[0].score_breakdown is not None
    assert "rerank" in out[0].score_breakdown
