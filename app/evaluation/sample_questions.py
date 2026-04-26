"""Curated example questions used in tests, the demo, and the README."""

from __future__ import annotations

SAMPLE_QUESTIONS: list[dict] = [
    {"intent": "business_model",         "text": "What does this company do?"},
    {"intent": "revenue_drivers",        "text": "What were the main revenue drivers?"},
    {"intent": "risk_analysis",          "text": "What risks does management disclose?"},
    {"intent": "margin_analysis",        "text": "Why did margins change?"},
    {"intent": "liquidity_analysis",     "text": "What does management say about liquidity?"},
    {"intent": "cross_year_comparison",  "text": "How did risk factors change compared with the prior year?"},
    {"intent": "segment_analysis",       "text": "What segments contributed most to growth?"},
    {"intent": "management_outlook",     "text": "What guidance or outlook did management provide?"},
    {"intent": "generic_filing_qa",      "text": "What uncertainties remain after reading the filing?"},
]
