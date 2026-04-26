"""Synthetic sample 10-K — fallback used only when no real filing is dropped
into ``data/sample_filings/``.

The real demo workflow expects a user-provided filing. This file exists so
tests and `make ingest-sample` work out of the box.
"""

from __future__ import annotations

from pathlib import Path

from app.core.logging import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample_filings"
SAMPLE_FILE = SAMPLE_DIR / "synthetic_10k.txt"

CONTENT = """ACME CORPORATION
Annual Report on Form 10-K
For the fiscal year ended December 31, 2025

PART I

Item 1. Business

Acme Corporation is a fictional industrial manufacturer that designs and
distributes precision components for the aerospace, automotive, and energy
markets. The company operates through three reportable segments: Aerospace
Components, Industrial Systems, and Energy Solutions. Acme's revenue is
generated primarily from long-term supply contracts with original equipment
manufacturers and after-market service agreements. The company sells its
products in over 30 countries and generated approximately $2.4 billion in
net sales for fiscal year 2025.

Item 1A. Risk Factors

Our business is subject to numerous risks. We summarize the principal
ones below; investors should consider these in conjunction with the
financial statements.

Macroeconomic conditions and inflation may adversely affect demand for our
products. A sustained increase in interest rates could increase our cost of
borrowing and reduce capital spending by our customers.

We face significant competition from larger, well-capitalized competitors
that may have greater resources and broader product portfolios. Failure to
innovate or to control costs could result in a loss of market share.

Our supply chain depends on a limited number of suppliers for certain
specialty alloys. Disruptions, including geopolitical sanctions and tariff
changes, could materially impact production schedules.

Cybersecurity incidents could compromise our information systems and the
confidential data of our customers. We have experienced attempted intrusions
in prior periods and expect threats to continue.

Climate-related regulation and customer expectations are increasing. We may
be required to make additional capital investments to reduce greenhouse-gas
emissions across our manufacturing footprint.

Item 3. Legal Proceedings

We are involved in routine litigation arising in the ordinary course of
business. While the outcomes of these matters are inherently uncertain, we
do not currently expect any of them, individually or in the aggregate, to
have a material adverse effect on our results of operations.

PART II

Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations

Net sales increased 6.2% year-over-year, from $2.26 billion to $2.40 billion,
driven by strong demand in the Aerospace Components segment and modest
volume gains in Energy Solutions. Pricing actions implemented in the second
half of fiscal 2024 contributed approximately 1.8 percentage points of the
year-over-year revenue growth.

Gross margin contracted by 90 basis points to 31.4%. The decline reflected
higher input costs for specialty alloys and unfavorable product mix in the
Industrial Systems segment, partially offset by manufacturing efficiencies.

Operating margin was 12.7%, down 60 basis points compared with the prior
year. Selling, general and administrative expense grew faster than revenue
due to investment in our digital aftermarket platform. Research and
development expense was 3.4% of net sales versus 3.2% in the prior year,
reflecting continued investment in next-generation aerospace components.

Liquidity and Capital Resources

We ended the year with $612 million in cash and cash equivalents and
undrawn capacity of $750 million on our revolving credit facility. Net
cash provided by operating activities was $358 million. Capital
expenditures were $192 million, primarily related to capacity expansion at
our Mexicali facility. We returned $215 million to shareholders through
share repurchases and dividends.

Outlook

For fiscal year 2026, management currently expects net sales growth in the
mid-single-digit range, with continued pressure on input costs offset by
pricing and mix actions. The company will continue to invest in capacity
and digital aftermarket capabilities. Forward-looking statements involve
risks and uncertainties; actual results may differ materially.

Item 8. Financial Statements

Consolidated Statements of Operations
Years ended December 31

(in millions, except per share)
                                  2025      2024      2023
Net sales                       2,400     2,260     2,150
Cost of sales                  (1,646)   (1,524)   (1,461)
Gross profit                      754       736       689
SG&A                             (382)     (351)     (325)
R&D                               (82)      (72)      (68)
Operating income                  290       313       296
Interest expense                  (38)      (35)      (33)
Income tax expense                (54)      (60)      (58)
Net income                        198       218       205

Diluted EPS                      4.12      4.55      4.27

Notes to Financial Statements

The accompanying consolidated financial statements have been prepared in
accordance with U.S. GAAP. Estimates and judgments are required. Significant
accounting policies are described in Note 2.

Segment Information

Aerospace Components contributed $1,180M of net sales (49%); Industrial
Systems $760M (32%); and Energy Solutions $460M (19%). Aerospace Components
operating profit grew 11% year-over-year while Industrial Systems operating
profit declined 7%.

Item 9A. Controls and Procedures

Our management, including the Chief Executive Officer and Chief Financial
Officer, evaluated the effectiveness of our disclosure controls and
procedures as of the end of the period and concluded they were effective.
"""


def main(force: bool = False) -> Path:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    if SAMPLE_FILE.exists() and not force:
        log.info("synthetic sample already exists", path=str(SAMPLE_FILE))
        return SAMPLE_FILE
    SAMPLE_FILE.write_text(CONTENT, encoding="utf-8")
    log.info("synthetic sample written", path=str(SAMPLE_FILE), bytes=len(CONTENT))
    return SAMPLE_FILE


if __name__ == "__main__":
    main(force=True)
