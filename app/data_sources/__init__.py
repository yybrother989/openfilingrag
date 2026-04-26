"""External data-source clients.

Tiered:
* Tier 1 (default, free): :class:`SECEdgarClient` — pulls 10-K/10-Q/8-K text.
* Tier 2 (optional, 2-of-a-choice): :class:`AlphaVantageClient` and
  :class:`MassiveClient` — provide earnings transcripts, news, and
  structured fundamentals when configured.
"""

from .alpha_vantage import AlphaVantageClient
from .base import (
    CompanyFinancials,
    CompanyOverview,
    DataSource,
    FilingNewsItem,
    ProvidersBundle,
)
from .massive import MassiveClient
from .sec_edgar import FilingRef, SECEdgarClient

__all__ = [
    "AlphaVantageClient",
    "CompanyFinancials",
    "CompanyOverview",
    "DataSource",
    "FilingNewsItem",
    "FilingRef",
    "MassiveClient",
    "ProvidersBundle",
    "SECEdgarClient",
]
