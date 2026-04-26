"""Optional LLM-based reranker.

In real mode, sends the top-K candidates to the LLM with the user query
and asks for a re-ranked subset. In mock mode, this is a no-op pass-through.
The graph workflow only invokes this if ``settings.is_mock_mode`` is False
and the candidate pool exceeds ``min_for_rerank``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.schemas.evidence import EvidenceItem

if TYPE_CHECKING:
    from app.services.llm_service import LLMService

log = get_logger(__name__)


class LLMReranker:
    def __init__(self, llm_service: "LLMService", min_for_rerank: int = 10) -> None:
        self.llm = llm_service
        self.min_for_rerank = min_for_rerank

    def rerank(
        self,
        query: str,
        items: list[EvidenceItem],
        top_n: int = 8,
    ) -> list[EvidenceItem]:
        if self.llm.provider_name == "mock":
            return items[:top_n]
        if len(items) < self.min_for_rerank:
            return items[:top_n]

        listing = "\n".join(
            f"[{i}] section={e.section} score={e.relevance_score:.2f}\n{e.text[:400]}"
            for i, e in enumerate(items)
        )
        try:
            payload = self.llm.chat_json(
                system=(
                    "You rerank retrieved filing snippets by relevance to the question. "
                    "Return JSON {\"order\": [<indices>]} listing the most relevant first."
                ),
                user=f"Question: {query}\n\nCandidates:\n{listing}",
                schema_hint='{"order": [int, ...]}',
            )
            order = payload.get("order") or []
            seen: set[int] = set()
            ranked: list[EvidenceItem] = []
            for idx in order:
                if isinstance(idx, int) and 0 <= idx < len(items) and idx not in seen:
                    ranked.append(items[idx])
                    seen.add(idx)
                if len(ranked) >= top_n:
                    break
            # Append any unscored leftovers in original order
            for i, e in enumerate(items):
                if i not in seen and len(ranked) < top_n:
                    ranked.append(e)
            return ranked
        except Exception as e:
            log.warning("rerank failed, falling back to original order", err=str(e))
            return items[:top_n]
