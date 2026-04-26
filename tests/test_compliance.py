"""Compliance policy: refuse advice queries, scrub restricted phrases."""

from __future__ import annotations

import pytest

from app.graph.policies import (
    REFUSAL_MESSAGE,
    find_restricted_phrases,
    is_advice_query,
)


@pytest.mark.parametrize(
    "query",
    [
        "Should I buy this stock?",
        "Should I sell ACME?",
        "What's the price target?",
        "Give me a buy rating",
        "Is this stock going to rally?",
    ],
)
def test_advice_queries_are_refused(query) -> None:
    assert is_advice_query(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "What does the company do?",
        "Why did margins decline?",
        "What risks does management disclose?",
        "Compare 2024 vs 2025 revenue.",
    ],
)
def test_research_queries_are_allowed(query) -> None:
    assert is_advice_query(query) is False


def test_restricted_phrases_in_text() -> None:
    text = (
        "Our analysis suggests you should buy this stock and target a price target of $150. "
        "We also recommend buying additional shares."
    )
    matches = find_restricted_phrases(text)
    assert any("buy this stock" in m.lower() for m in matches)
    assert any("price target" in m.lower() for m in matches)
    assert any("recommend buying" in m.lower() for m in matches)


def test_refusal_message_is_canonical() -> None:
    assert "investment advice" in REFUSAL_MESSAGE.lower()
    assert "ratings" in REFUSAL_MESSAGE.lower()
    assert "price targets" in REFUSAL_MESSAGE.lower()
