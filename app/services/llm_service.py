"""LLM service with pluggable providers.

Three providers:
* ``OpenAIProvider`` — chat completions (defaults to ``gpt-4o-mini``)
* ``AnthropicProvider`` — messages API (defaults to ``claude-haiku-4-5``)
* ``MockProvider`` — deterministic, template-driven outputs for tests/demos

All providers expose two methods:
* :meth:`chat_json` — returns a parsed JSON object (used by classify/plan/generate)
* :meth:`chat_stream` — yields text tokens (used by streaming generate)
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any, Protocol

from app.core.config import settings
from app.core.errors import LLMError
from app.core.logging import get_logger

log = get_logger(__name__)


class _LLMProvider(Protocol):
    name: str

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]: ...

    def chat_stream(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
    ) -> Iterator[str]: ...


# ---------------------------------------------------------------------
# Mock provider — deterministic responses derived from prompt patterns
# ---------------------------------------------------------------------
class MockProvider:
    """Returns canned JSON for known prompt prefixes; templated text for streams.

    Designed to make end-to-end workflow tests deterministic without
    network calls.
    """

    name = "mock"

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        s = system.lower()
        u = user.lower()
        combined = f"{s}\n{u}"

        # Compliance refusal (advice question)
        if any(p in u for p in ("should i buy", "should i sell", "price target", "buy or sell")):
            return {"intent": "refused_advice"}

        # classify_query
        if "classify" in combined and "intent" in combined:
            intent = self._guess_intent(user)
            return {
                "intent": intent,
                "ticker": self._guess_ticker(user),
                "fiscal_year": self._guess_year(user),
                "company_name": None,
                "wants_cross_year": "compared" in u or "year over year" in u or "yoy" in u,
            }

        # generate_report
        if "generate" in combined and "report" in combined:
            return self._mock_report_payload(user)

        # validate_report
        if "validate" in combined or "compliance" in combined:
            return {"compliant": True, "warnings": []}

        # Fallback
        return {"summary": "Mock response.", "intent": "generic_filing_qa"}

    def chat_stream(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        text = "Based on the supplied evidence, the filings indicate the points listed below. " \
               "All claims trace to the cited evidence; no investment advice is provided."
        for word in text.split(" "):
            yield word + " "

    # ---- helpers ----
    @staticmethod
    def _guess_intent(text: str) -> str:
        t = text.lower()
        if any(k in t for k in ("risk", "litigation", "lawsuit")):
            return "risk_analysis"
        if "margin" in t:
            return "margin_analysis"
        if any(k in t for k in ("liquidity", "cash flow", "debt")):
            return "liquidity_analysis"
        if any(k in t for k in ("revenue driver", "what drove", "top line")):
            return "revenue_drivers"
        if "segment" in t:
            return "segment_analysis"
        if any(k in t for k in ("guidance", "outlook", "forward-looking")):
            return "management_outlook"
        if any(k in t for k in ("compared with", "year over year", "yoy", "vs prior year")):
            return "cross_year_comparison"
        if any(k in t for k in ("what does", "what do they do", "business model", "company do")):
            return "business_model"
        if any(k in t for k in ("revenue", "income", "balance sheet", "cash flow statement")):
            return "financial_statement_lookup"
        return "generic_filing_qa"

    @staticmethod
    def _guess_ticker(text: str) -> str | None:
        # Look for $TICKER or 1-5 uppercase letter tokens preceded by "for"/"about"
        m = re.search(r"\$([A-Z]{1,5})\b", text)
        if m:
            return m.group(1)
        m = re.search(r"\b(?:for|about|of)\s+([A-Z]{1,5})\b", text)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _guess_year(text: str) -> int | None:
        m = re.search(r"\b(20\d{2})\b", text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _mock_report_payload(user_query: str) -> dict[str, Any]:
        return {
            "summary": (
                "Synthesized from filing evidence (mock mode). "
                "Each finding below cites the supporting chunk by source_id."
            ),
            "key_findings": [
                {
                    "claim": "The company describes its operating segments and revenue mix in the Business and Segment Information sections.",
                    "evidence_ids": [],
                    "confidence": "medium",
                    "reasoning_summary": "Drawn from Business / Segment sections.",
                }
            ],
            "financial_metrics": [],
            "risk_factors": [],
            "management_commentary": [],
            "limitations": [
                "Mock-mode synthesis — set OPENAI_API_KEY for real LLM-based reasoning.",
            ],
        }


# ---------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------
class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError("openai package required for OpenAIProvider") from e
        self._client = OpenAI(api_key=api_key or settings.openai_api_key)
        self.model = model or settings.llm_model or "gpt-4o-mini"

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        prompt_user = user
        if schema_hint:
            prompt_user = f"{user}\n\nReturn JSON matching this schema:\n{schema_hint}"
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt_user},
                ],
            )
        except Exception as e:
            raise LLMError(f"OpenAI chat call failed: {e}") from e
        content = resp.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"OpenAI returned non-JSON: {content[:200]}") from e

    def chat_stream(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                stream=True,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as e:
            raise LLMError(f"OpenAI stream call failed: {e}") from e
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta


# ---------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------
class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise LLMError("anthropic package required for AnthropicProvider") from e
        self._client = Anthropic(api_key=api_key or settings.anthropic_api_key)
        self.model = model or settings.llm_model or "claude-haiku-4-5"

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        prompt_user = user
        if schema_hint:
            prompt_user = f"{user}\n\nRespond with valid JSON only matching:\n{schema_hint}"
        try:
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=2048,
                temperature=temperature,
                system=system + "\nRespond with valid JSON only.",
                messages=[{"role": "user", "content": prompt_user}],
            )
        except Exception as e:
            raise LLMError(f"Anthropic call failed: {e}") from e
        text = "".join(block.text for block in msg.content if hasattr(block, "text"))
        # Strip code fences if present
        text = re.sub(r"^```(?:json)?\n?", "", text.strip()).rstrip("`").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"Anthropic returned non-JSON: {text[:200]}") from e

    def chat_stream(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        try:
            with self._client.messages.stream(
                model=self.model,
                max_tokens=2048,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                for token in stream.text_stream:
                    yield token
        except Exception as e:
            raise LLMError(f"Anthropic stream failed: {e}") from e


# ---------------------------------------------------------------------
# Service facade
# ---------------------------------------------------------------------
class LLMService:
    """Single entry point for LLM calls; auto-selects provider via settings."""

    def __init__(self, provider: _LLMProvider | None = None) -> None:
        if provider is not None:
            self._provider: _LLMProvider = provider
        else:
            self._provider = self._build_default()
        log.info("llm service ready", provider=self._provider.name)

    @staticmethod
    def _build_default() -> _LLMProvider:
        name = settings.effective_llm_provider
        if name == "openai":
            return OpenAIProvider()
        if name == "anthropic":
            return AnthropicProvider()
        return MockProvider()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        return self._provider.chat_json(
            system, user, schema_hint=schema_hint, temperature=temperature
        )

    def chat_stream(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        return self._provider.chat_stream(system, user, temperature=temperature)
