"""Deterministic chat model for tests / demos / mock mode.

A minimal :class:`BaseChatModel` subclass that intentionally **only**
supports ``.with_structured_output(...)``. Calling ``.invoke()`` /
``_generate()`` directly raises so any new code path that bypasses the
structured-output contract fails loudly instead of getting silently
mocked into something meaningless.

Canned responses are picked by inspecting the schema name and keywords
in the messages — same heuristic as the deleted
``LLMService.MockProvider`` so existing test fixtures keep working.
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from app.schemas.query import ResearchIntent


class MockChatModel(BaseChatModel):
    """Returns canned structured outputs for tests/demos.

    Only ``.with_structured_output(schema)`` is supported. Anything
    else routes through ``_generate`` which raises so we don't silently
    mock a code path that hasn't been thought through.
    """

    @property
    def _llm_type(self) -> str:
        return "mock-chat"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError(
            "MockChatModel only supports .with_structured_output(schema). "
            "Free-text generation is intentionally not stubbed."
        )

    def with_structured_output(
        self,
        schema: type[BaseModel] | None = None,
        **_kwargs: Any,
    ) -> Runnable:
        if schema is None or not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise ValueError("MockChatModel.with_structured_output requires a Pydantic schema")
        return RunnableLambda(lambda messages: _canned_for_schema(schema, messages))


# ----------------------------------------------------------------------
# Canned-response heuristics — mirror the deleted MockProvider
# ----------------------------------------------------------------------
def _canned_for_schema(schema: type[BaseModel], messages: Any) -> BaseModel:
    text = _flatten_messages(messages).lower()
    name = schema.__name__

    if name == "LLMClassifyOutput":
        return schema(
            intent=_guess_intent(text),
            ticker=_guess_ticker(text),
            company_name=None,
            fiscal_year=_guess_year(text),
            wants_cross_year=any(k in text for k in ("compared", "year over year", "yoy", "vs prior year")),
        )

    if name == "LLMReportDraft":
        # Cite [1] on the canned finding so validate passes when there's
        # at least one evidence chunk in the prompt.
        return schema(
            summary=(
                "Synthesized from filing evidence (mock mode). "
                "Each finding cites the supporting chunk by number."
            ),
            key_findings=[
                {
                    "claim": "The company describes its operating segments and revenue mix in the filing.",
                    "evidence_numbers": [1],
                    "confidence": "medium",
                    "reasoning_summary": "Drawn from supplied citations.",
                }
            ],
            financial_metrics=[],
            risk_factors=[],
            management_commentary=[],
            limitations=[
                "Mock-mode synthesis — set OPENAI_API_KEY for real LLM-based reasoning.",
            ],
        )

    # Fallback for any future schema — empty model so callers see the shape.
    return schema()


def _flatten_messages(messages: Any) -> str:
    """Coerce whatever the caller passed to ``.invoke()`` into a string,
    keeping only the user-role content. The system prompt is full of
    classifier hints (e.g. "risk_analysis") that would otherwise leak
    into the keyword heuristics and make every query look like a risk
    question."""
    if isinstance(messages, str):
        return messages
    if isinstance(messages, list):
        parts: list[str] = []
        for m in messages:
            if isinstance(m, dict):
                role = m.get("role") or m.get("type")
                if role and role != "user" and role != "human":
                    continue
                parts.append(str(m.get("content") or ""))
            elif isinstance(m, BaseMessage):
                if m.type not in ("human", "user"):
                    continue
                parts.append(str(m.content or ""))
            else:
                parts.append(str(m))
        return "\n".join(parts)
    return str(messages)


def _guess_intent(text: str) -> ResearchIntent:
    if any(k in text for k in ("risk", "litigation", "lawsuit")):
        return ResearchIntent.RISK_ANALYSIS
    if "margin" in text:
        return ResearchIntent.MARGIN_ANALYSIS
    if any(k in text for k in ("liquidity", "cash flow", "debt")):
        return ResearchIntent.LIQUIDITY_ANALYSIS
    if any(k in text for k in ("revenue driver", "what drove", "top line")):
        return ResearchIntent.REVENUE_DRIVERS
    if "segment" in text:
        return ResearchIntent.SEGMENT_ANALYSIS
    if any(k in text for k in ("guidance", "outlook", "forward-looking")):
        return ResearchIntent.MANAGEMENT_OUTLOOK
    if any(k in text for k in ("compared with", "year over year", "yoy", "vs prior year")):
        return ResearchIntent.CROSS_YEAR_COMPARISON
    if any(k in text for k in ("what does", "what do they do", "business model", "company do")):
        return ResearchIntent.BUSINESS_MODEL
    if any(k in text for k in ("revenue", "income", "balance sheet", "cash flow statement")):
        return ResearchIntent.FINANCIAL_STATEMENT_LOOKUP
    return ResearchIntent.GENERIC_FILING_QA


def _guess_ticker(text: str) -> str | None:
    m = re.search(r"\$([A-Z]{1,5})\b", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b(?:for|about|of)\s+([A-Z]{1,5})\b", text)
    if m:
        return m.group(1).upper()
    return None


def _guess_year(text: str) -> int | None:
    m = re.search(r"\b(20\d{2})\b", text)
    return int(m.group(1)) if m else None
