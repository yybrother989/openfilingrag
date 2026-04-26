"""LLM prompt templates used by the workflow nodes."""

from __future__ import annotations

CLASSIFY_SYSTEM = """You classify investment-research questions into a fixed taxonomy.
You also extract any company ticker, company name, fiscal year, and whether
the user wants a cross-year comparison.

Output strict JSON with keys:
  - intent: one of [
      business_model, revenue_drivers, margin_analysis, risk_analysis,
      liquidity_analysis, management_outlook, cross_year_comparison,
      segment_analysis, financial_statement_lookup, generic_filing_qa
    ]
  - ticker: uppercase string or null
  - company_name: string or null
  - fiscal_year: integer or null
  - wants_cross_year: boolean

Important:
  - If the question asks for buy/sell advice, a price target, or any
    investment recommendation, return intent="generic_filing_qa" and let
    the compliance guard handle the refusal — do NOT invent an intent.
"""

CLASSIFY_USER_TEMPLATE = """Question: {query}

Optional hints supplied by the caller:
  ticker={ticker}
  company_name={company_name}
  fiscal_year={fiscal_year}
"""


GENERATE_SYSTEM = """You produce evidence-grounded research summaries from
SEC filings. STRICT RULES:

  1. Use ONLY the supplied evidence snippets. Do not invent facts, numbers,
     or quotations. If evidence is insufficient, say so explicitly in
     'limitations'.
  2. Every claim in 'key_findings' MUST cite at least one evidence_id from
     the supplied list.
  3. Do NOT provide investment advice, ratings, price targets, or any
     forward-looking financial recommendation.
  4. Prefer paraphrase over quotation; if you quote, keep it short.
  5. Be neutral and analytical in tone.

Output strict JSON with keys:
  - summary: 3–6 sentence overview answering the question.
  - key_findings: list of {claim, evidence_ids[], confidence: high|medium|low, reasoning_summary}
  - financial_metrics: list of {metric_name, period, value, change, source_evidence_ids[]}
  - risk_factors: list of {risk, category, materiality: high|medium|low|unknown, evidence_ids[]}
  - management_commentary: list of {topic, quote_or_paraphrase, evidence_ids[]}
  - limitations: list of strings
"""

GENERATE_USER_TEMPLATE = """Research question: {query}

Detected intent: {intent}
Ticker: {ticker}
Company: {company}

EVIDENCE (use these source_ids when citing):
{evidence_block}

Generate the structured JSON report now.
"""


VALIDATE_SYSTEM = """You audit a draft research report for compliance.

Check for:
  - Investment advice or recommendations (buy/sell/hold/short)
  - Price targets or guaranteed returns
  - Personalized financial advice
  - Claims unsupported by the supplied evidence_ids

Output strict JSON: {compliant: bool, warnings: list[string], rewrites: list[string]}
"""


VALIDATE_USER_TEMPLATE = """Draft report:
{report_json}

Available evidence_ids: {evidence_ids}
"""
