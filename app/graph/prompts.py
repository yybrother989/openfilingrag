"""LLM prompt templates used by the workflow nodes.

Phase 4: shape and JSON description live in the Pydantic schemas
(``LLMClassifyOutput`` / ``LLMReportDraft`` in :mod:`.llm_schemas`),
so the prompts focus on **rules and grounding** rather than format.
"""

from __future__ import annotations


# ----------------------------------------------------------------------
# classify_query
# ----------------------------------------------------------------------
CLASSIFY_SYSTEM = """You classify investment-research questions into a fixed taxonomy.
You also extract any company ticker, company name, fiscal year, and whether
the user wants a cross-year comparison.

Allowed intents:
  business_model, revenue_drivers, margin_analysis, risk_analysis,
  liquidity_analysis, management_outlook, cross_year_comparison,
  segment_analysis, financial_statement_lookup, generic_filing_qa.

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


# ----------------------------------------------------------------------
# generate_report
# ----------------------------------------------------------------------
GENERATE_SYSTEM = """You produce evidence-grounded research summaries from
SEC filings. STRICT RULES:

  1. Use ONLY the supplied citation chunks. Do not invent facts, numbers,
     or quotations. If the supplied chunks are insufficient to answer the
     question, say so explicitly in 'limitations'.
  2. Do NOT provide investment advice, ratings, price targets, or any
     forward-looking financial recommendation.
  3. Prefer paraphrase over quotation; if you quote, keep it short.
  4. Be neutral and analytical in tone.
  5. Sections you don't have evidence for should be left empty rather
     than padded with speculation.

GROUNDING RULES — non-negotiable:
  - You ONLY have access to the user query and the numbered citation
    chunks below. There is no external knowledge in scope.
  - Cite by bracketed numbers like [3] referring to the citation chunks.
    Never invent numbers; never use any other id format (no UUIDs, no
    page numbers, no source_id strings).
  - Every claim in key_findings, every entry in financial_metrics, every
    risk_factor, and every management_commentary MUST include at least
    one number in its evidence_numbers list. If you cannot cite, omit
    the claim and add a note to limitations explaining what's missing.
"""

GENERATE_USER_TEMPLATE = """Research question: {query}

Detected intent: {intent}
Ticker: {ticker}
Company: {company}

CITATION CHUNKS (cite ONLY by these numbers in evidence_numbers):
{evidence_block}
"""


# Appended to the user prompt on a self-correction retry. ``issues`` is
# a bullet-list of concrete problems the validate node found.
REVISION_FEEDBACK_TEMPLATE = """The previous draft was rejected for these issues:
{issues}

Produce a corrected draft that fixes ALL of the above. Use ONLY the
citation numbers shown above — do not invent numbers, do not omit
citations on claims. If a claim cannot be cited, drop it instead of
keeping it without a citation."""
