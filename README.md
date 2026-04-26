<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="logo/chorusai_logo_horizontal_dark.png">
    <img alt="OpenFilingRAG" src="logo/chorusai_logo_horizontal_light.png" width="420">
  </picture>
</p>

# OpenFilingRAG

<p align="center">
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue.svg">
  <img alt="Postgres + pgvector" src="https://img.shields.io/badge/postgres-pgvector-3178c6.svg">
</p>

> **OpenFilingRAG is a dynamic, filing-aware RAG prototype for parsing
> company filings into structured sections, routing investment-research
> questions to relevant evidence, and generating source-grounded company
> research summaries.**

> ⚠️ This prototype summarizes company disclosures. It does **not** provide
> investment advice, ratings, or price targets. See the
> [Compliance disclaimer](#compliance-disclaimer) below.

OpenFilingRAG is an open-source technical prototype built to demonstrate a
research-grade RAG pipeline for SEC filings (10-K, 10-Q, annual reports,
earnings docs, investor presentations). Unlike a generic "PDF chatbot,"
the system makes retrieval decisions based on **document structure**
(canonical filing sections), **user intent** (classified into a fixed
taxonomy), and **hybrid scoring** (vector + keyword + section + source +
recency) — then orchestrates the research workflow with **LangGraph** and
streams structured agent events to an **assistant-ui** frontend in real
time.

---

## Why this is different from a generic PDF RAG

A generic PDF RAG embeds everything and runs cosine similarity. That
fails for filings because:

* **Structure matters more than similarity.** "What are the key risks?"
  should pull from *Item 1A · Risk Factors*, not from any paragraph that
  happens to mention "risk."
* **Intent shapes scope.** "Why did margins decline?" should prioritize
  *MD&A*, the income statement, and segment notes — not the cover page.
* **Citations are mandatory.** Every claim in a research summary must
  point back to specific evidence the reader can verify.
* **Compliance is non-optional.** No buy/sell language. No price targets.
  No personalized advice.

OpenFilingRAG addresses each of these explicitly:

| Concern | OpenFilingRAG approach |
|---|---|
| Structure-aware retrieval | A heuristic section splitter detects ~15 canonical filing sections (Item 1, Item 1A, Item 7, etc.). Chunks inherit section + page + content_type metadata and become first-class filters. |
| Intent routing | A query classifier maps questions to one of 10 research intents. Each intent has a `RetrievalPolicy` declaring preferred sections, document types, content types, term expansions, top_k, and table priority. |
| Hybrid scoring | `score = 0.45 · vector + 0.30 · keyword + 0.10 · section_match + 0.10 · source_priority + 0.05 · recency`. Each chunk carries a `score_breakdown` so the UI can explain *why* it was retrieved. |
| Evidence-grounded synthesis | The `generate_report` node prompts the LLM to cite `evidence_id`s for every claim. The `validate_report` node rejects findings that lack citations. |
| Compliance | Pre-query guard refuses advice questions outright. A post-generation regex pass scrubs leaked language. The canonical refusal message is hard-coded. |

---

## Architecture

```
                 ┌────────────────┐
                 │  Next.js +     │  3-panel terminal:
                 │  assistant-ui  │   ◀  control · timeline · evidence
                 └───────┬────────┘
                         │ POST /research/stream  (SSE)
                         ▼
       ┌──────────────────────────────────┐
       │  FastAPI                         │
       │  ─ /research/query  (sync)       │
       │  ─ /research/stream (SSE)        │
       │  ─ /documents/ingest             │
       │  ─ /companies/{ticker}/enrich    │
       │  ─ /evidence/{source_id}         │
       └──────────────┬───────────────────┘
                      │
                      ▼
       ┌──────────────────────────────────┐
       │  LangGraph workflow              │
       │   classify_query                 │
       │   ↓ plan_retrieval               │
       │   ↓ retrieve_evidence  ─── Hybrid retriever ──┐
       │   ↓ verify_evidence                           │
       │   ↓ generate_report  ──── LLM service ────────│
       │   ↓ validate_report                           │
       │   ↓ format_output                             │
       └──────┬─────────────┬──────────────────────────┘
              │             │
              ▼             ▼
   ┌────────────────┐  ┌────────────────────┐
   │ External data  │  │  Postgres + pgvector │
   │ Alpha Vantage  │  │  · companies         │
   │ Massive        │  │  · documents         │
   └────────────────┘  │  · document_sections │
                       │  · document_chunks   │
                       │  · financial_tables  │
                       │  · research_reports  │
                       │  · evidence_items    │
                       └──────────────────────┘
```

### Data flow (ingest → query)

```
PDF/HTML/TXT
   │
   │  PDFParser / HTMLParser / TextParser
   ▼
ParsedDocument (full_text + page map)
   │
   │  SectionSplitter  →  DetectedSection[]
   │  TableExtractor   →  ExtractedTable[]
   ▼
Chunker  →  Chunk[] (section + page span preserved)
   │
   │  MetadataEnricher  →  content_type, metric_tags, risk_tags
   │  EmbeddingService  →  1536-d vectors (or 128-d hash in mock mode)
   ▼
Postgres: companies → documents → sections → chunks (+ tables)

──────────────────────────────────────────────────────────

User question
   │
   ▼  POST /research/stream
classify_query  ──emits──▶  query_classified event
   │
   ▼
plan_retrieval  ──emits──▶  retrieval_plan, section_selected events
   │
   ▼
retrieve_evidence ──emits──▶  evidence_found events (one per chunk)
   │   │
   │   └─ HybridRetriever  →  metadata filter + vector + keyword fusion
   ▼
verify_evidence ──emits──▶  verification_warning events
   │
   ▼
generate_report ──emits──▶  report_section events
   │   │
   │   └─ LLM with strict "cite or refuse" prompt
   ▼
validate_report ──emits──▶  more verification_warning events on issues
   │
   ▼
format_output  ──emits──▶  final_report + run_completed events
```

### Dynamic RAG workflow (intent routing)

| Question | Intent | Sections boosted | Doc types | Tables prioritized |
|---|---|---|---|---|
| "What does this company do?" | `business_model` | Business, Segment Information | 10-K, annual_report | — |
| "What were the main revenue drivers?" | `revenue_drivers` | MD&A, Segment Information, Business | 10-K/10-Q | ✓ |
| "Why did margins change?" | `margin_analysis` | MD&A, Financial Statements, Notes, Segment | 10-K/10-Q | ✓ |
| "What risks does management disclose?" | `risk_analysis` | Risk Factors, Legal Proceedings, MD&A | 10-K/10-Q | — |
| "What about liquidity?" | `liquidity_analysis` | Liquidity, Financial Statements, Notes, MD&A | 10-K/10-Q | ✓ |
| "What does management expect?" | `management_outlook` | MD&A, Outlook | 10-K/10-Q + transcripts + presentations | — |
| "How did risks change YoY?" | `cross_year_comparison` | Risk Factors, MD&A, Segment, Liquidity | 10-K | — (cross-year) |
| "Which segment grew fastest?" | `segment_analysis` | Segment Information, MD&A | 10-K/10-Q | ✓ |
| Restricted phrasing ("should I buy/sell…") | `refused_advice` | — | — | refusal returned |

The full mapping lives in [`app/graph/policies.py`](app/graph/policies.py).

---

## Supported document types

| Format | Parser | Notes |
|---|---|---|
| `.pdf` | PyMuPDF + pdfplumber | Page-aware text + table extraction |
| `.html` / `.htm` | BeautifulSoup (`lxml`) | Strips nav/footer chrome |
| `.txt` / `.md` | Plain | Single-page fallback |

Document type is supplied at ingest time: `10-K`, `10-Q`, `8-K`,
`annual_report`, `earnings_transcript`, `investor_presentation`,
`press_release`, `other`.

---

## Data sources — three tiers

OpenFilingRAG is designed so that **forking the repo and running `make
edgar-pull TICKER=AAPL` is enough to start doing real research** — no
API key required. Optional providers add richer text (transcripts, news,
fundamentals) but are never mandatory.

| Tier | Source | Key required | What it gives you | Default state |
|---|---|---|---|---|
| **0 — manual** | files dropped into [`data/sample_filings/`](data/sample_filings/README.md) | no | private docs, board decks, non-SEC filings | always available |
| **1 — SEC EDGAR** | `data.sec.gov` + `www.sec.gov/Archives/...` | **no** (just a User-Agent) | full text of 10-K, 10-Q, 8-K (and amendments) for any US-listed ticker | **on by default** |
| **2 — optional enrichment** *(pick at most one)* | **Alpha Vantage** *or* **Massive** | yes (free tier) | earnings call transcripts, news + sentiment, structured income/balance/cash flow | off until you set a key |

### Tier 1 — SEC EDGAR (free, default)

Pulls real filings by ticker. **No API key. Free. Official.** SEC requires
a `User-Agent` that identifies you ([policy](https://www.sec.gov/os/accessing-edgar-data));
set `SEC_EDGAR_USER_AGENT="Your Name your@email.com"` in `.env`.

```bash
# pull the latest 10-K for Apple and ingest it
make edgar-pull TICKER=AAPL TYPES=10-K LIMIT=1

# pull the last 4 quarterly filings for Microsoft
make edgar-pull TICKER=MSFT TYPES=10-Q LIMIT=4

# all recent 8-Ks since a date
python -m scripts.edgar_pull TSLA --types 8-K --since 2025-01-01
```

Behind the scenes:
- Resolves ticker → CIK via SEC's [company tickers map](https://www.sec.gov/files/company_tickers.json) (cached 7 days under `data/edgar_cache/`)
- Lists recent filings via `https://data.sec.gov/submissions/CIK{cik:010d}.json`
- Downloads the primary document into `data/sample_filings/{ticker}/{accession}/`
- Auto-derives `document_type`, `fiscal_year`, `filing_date`, `source_url` and runs the existing ingestion pipeline
- Idempotent — re-running with the same params skips already-ingested filings

### Tier 2 — optional enrichment (Alpha Vantage **or** Massive — pick one)

Both providers cover the same ~95% of capabilities for our use case, so
configure **at most one**. Pick whichever you already have a key for.

| Capability | Alpha Vantage | Massive |
|---|---|---|
| Earnings call transcripts (long text — useful for `management_outlook`) | ✅ `EARNINGS_CALL_TRANSCRIPT` | ❌ |
| News + sentiment | ✅ `NEWS_SENTIMENT` (topic-filterable) | ✅ `/v2/reference/news` |
| Structured fundamentals (revenue, margins, cash flow) — useful for **fact-checking RAG answers** | ✅ `INCOME_STATEMENT` + `BALANCE_SHEET` + `CASH_FLOW` | ✅ `/vX/reference/financials` |
| Company overview (sector, industry, description) | ✅ `OVERVIEW` | ✅ `/v3/reference/tickers/{t}` |
| Macro indicators (CPI, GDP, rates) | ✅ | ❌ |
| Dividends / splits as discrete events | ❌ | ✅ |
| Free-tier limits | 5 req/min, 500 req/day | varies by plan |

Enable by adding **one** of these to `.env`:

```bash
ALPHA_VANTAGE_API_KEY=...   # https://www.alphavantage.co/support/#api-key
# or
MASSIVE_API_KEY=...         # https://massive.com
```

Once set, the `POST /companies/{ticker}/enrich` endpoint pulls company
overview, news, and fundamentals to backfill `companies.sector`/`industry`
and seed company descriptions.

### What the system does *not* require

- ❌ Any LLM API key (mock LLM + hash embedder run offline)
- ❌ Any external data API key (EDGAR is free)
- ❌ Anything beyond a free Supabase project + `make edgar-pull && make api`

Adding keys *upgrades* the experience — it never gates it.

---

## Quickstart

### Prerequisites

* Python 3.11+
* Node 20+ (for the frontend)
* A free [Supabase](https://supabase.com) project (hosts Postgres + pgvector)

### 1. Install Python deps

```bash
make install
cp .env.example .env
# Edit .env to set SEC_EDGAR_USER_AGENT (your name + email).
# Optional: add OPENAI_API_KEY for real LLM/embeddings,
#           and one of ALPHA_VANTAGE_API_KEY or MASSIVE_API_KEY.
```

### 2. Provision the database (Supabase)

1. Create a project at [supabase.com](https://supabase.com) (free tier is fine).
2. **Database → Extensions** → enable `vector` (`pg_trgm` and `pgcrypto` are on by default).
3. **SQL Editor** → paste the contents of [`app/db/migrations/001_init.sql`](app/db/migrations/001_init.sql) → Run. This creates 7 tables (companies, documents, document_sections, document_chunks, financial_tables, research_reports, evidence_items) with all indexes and the ivfflat vector index.
4. **Settings → Database → Connection string** → copy the **Session pooler** URI (port 5432).
   ⚠️ Don't use the Transaction pooler (6543) — it disables prepared statements and breaks SQLAlchemy.
5. Put it in `.env` as `DATABASE_URL`, replacing the `postgresql://` prefix with `postgresql+psycopg://` (SQLAlchemy needs the driver suffix). `sslmode=require` is auto-added if you omit it.

### 3. Pull a real filing from SEC EDGAR (no API key required)

```bash
make edgar-pull TICKER=AAPL TYPES=10-K LIMIT=1
```

This downloads Apple's latest 10-K, runs the full ingestion pipeline
(parse → split into ~14 canonical sections → chunk → embed → persist),
and stores it under `data/sample_filings/AAPL/`. Re-running is idempotent.

You can also drop a private filing (board deck, internal memo) directly
into `data/sample_filings/` and run `make ingest-sample` instead.

### 4. Start the backend + frontend

```bash
# terminal 1
make api      # http://localhost:8000  (FastAPI + SSE)

# terminal 2
make demo     # http://localhost:3000  (Next.js + assistant-ui)
```

### 5. Ask a question

Open <http://localhost:3000>. Try a sample question from the left panel, or
type something like "What were the main revenue drivers?". The center
panel will stream:

1. **Query classified** — detected intent, ticker, fiscal year
2. **Retrieval plan** — sections / doc types / metric expansions
3. **Sections selected** — explicit section badges
4. **Evidence retrieved** — count + per-chunk cards in the right panel
5. **Verification warnings** — if any
6. **Research memo** — structured summary, findings, metrics, risks, commentary

### 6. Run tests (works in mock mode, no API keys needed)

```bash
make test
```

---

## API usage

### Sync research query

```bash
curl -s -X POST http://localhost:8000/research/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the key risks?",
    "ticker": "AAPL",
    "fiscal_year": 2024
  }' | jq
```

### Streaming SSE endpoint

```bash
curl -N -X POST http://localhost:8000/research/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "What were the main revenue drivers?", "ticker": "AAPL"}'
```

You'll see SSE frames like:

```
event: run_started
id: 6f1c…
data: {"event_id":"6f1c…","run_id":"…","type":"run_started","payload":{…}}

event: query_classified
id: 8b2a…
data: {…,"payload":{"intent":"revenue_drivers","ticker":"AAPL",…}}

event: evidence_found
id: c91e…
data: {…,"payload":{"source_id":"…","section":"MD&A","page_start":42,…}}

event: final_report
…
```

### Document ingest

```bash
curl -X POST http://localhost:8000/documents/ingest \
  -F "ticker=AAPL" \
  -F 'company_name=Apple Inc.' \
  -F "document_type=10-K" \
  -F "fiscal_year=2024" \
  -F "filing_date=2024-08-01" \
  -F "source_priority=primary_filing" \
  -F "file=@./data/sample_filings/aapl-10k.pdf"
```

### List documents

```bash
curl http://localhost:8000/documents
curl http://localhost:8000/documents/1
```

### Look up evidence

```bash
curl http://localhost:8000/evidence/<source_id>
```

### Enrich a company via external providers

```bash
curl -X POST http://localhost:8000/companies/AAPL/enrich
```

---

## Frontend integration modes

### Mode A — Local FastAPI SSE (default, what `make demo` uses)

The Next.js app talks to FastAPI's `/research/stream` endpoint via the
custom adapter in [`frontend/lib/stream.ts`](frontend/lib/stream.ts). The
adapter parses SSE frames, dispatches events to the reducer in
[`frontend/lib/useResearchRun.ts`](frontend/lib/useResearchRun.ts), and the
UI renders structured event cards. This mode requires no LangGraph
Server deployment.

### Mode B — LangGraph Server + assistant-ui (optional advanced)

For multi-tenant or hosted deployments, you can compile the same workflow
as a LangGraph `StateGraph` (see
[`app/graph/workflow.py::build_langgraph`](app/graph/workflow.py)) and
deploy it to LangGraph Server. On the frontend, swap the custom adapter
for [`@assistant-ui/react-langgraph`](https://www.assistant-ui.com/docs/runtimes/langgraph)
and point it at the deployment.

In Mode B the graph state's `messages` key (a LangChain-style list of
HumanMessage/AIMessage objects) is what assistant-ui drives. We expose
the workflow nodes as LangGraph nodes precisely so this swap is
mechanical — the event protocol is the same.

---

## Project layout

```
app/
  core/               config, logging, errors
  api/                FastAPI routers
  db/                 ORM models + 001_init.sql migration
  schemas/            Pydantic v2 contracts (events, evidence, report, query, graph_state)
  ingestion/          PDF/HTML parsers, section splitter, chunker, table extractor
  retrieval/          metadata filter, vector store, keyword search, hybrid retriever
  graph/              LangGraph nodes, workflow, event emitter, policies, prompts
  services/           embedding_service, llm_service, company_enrichment, document_service
  data_sources/       Alpha Vantage + Massive REST clients
  evaluation/         simple metrics + sample questions

frontend/
  app/page.tsx                  3-panel terminal layout
  components/
    ResearchControls.tsx        left panel: query box, controls, sample questions
    EventTimeline.tsx           center panel: structured event cards
    ReportCard.tsx              final research memo card
    EvidenceInspector.tsx       right panel: live evidence updates
  lib/
    stream.ts                   custom SSE adapter
    useResearchRun.ts           run state machine
    types.ts                    mirror of Python schemas

scripts/
  ingest_sample.py              auto-discover + ingest a real filing
  create_sample_report.py       fallback synthetic 10-K for offline tests
  edgar_pull.py                 pull + ingest filings from SEC EDGAR by ticker

tests/                          pytest, all run in mock mode (no API keys)

Makefile                        canonical commands
```

---

## Mock mode

If neither `OPENAI_API_KEY` nor `ANTHROPIC_API_KEY` is set:

* `LLMService` uses `MockProvider` → deterministic templated JSON responses
* `EmbeddingService` uses `HashEmbedder` → 1536-d vectors derived from
  SHA-256-bucketed token hashes (still gives meaningful relative ordering
  for retrieval)
* The frontend shows a yellow `MOCK MODE` banner

This makes tests and demos reproducible offline. **For real research, set
your own API keys** — the mock mode does not actually reason about your
filings.

---

## Limitations (be honest about what this is)

* **Section detection** is regex-based. It works well on standard
  10-Ks/10-Qs and degrades gracefully on quirky layouts, but you should
  expect occasional misses on mid-size or non-US filings.
* **Table extraction** is best-effort via pdfplumber; complex multi-page
  tables and merged cells may parse imperfectly.
* **No XBRL / iXBRL** parsing — semantically tagged numbers from EDGAR
  are not consumed.
* **No real-time price/quote data**.
* **No full SEC EDGAR fetching loop** — bring your own filing for now.
* **The synthetic fallback filing** is a 1-page mock and is not
  representative of real 10-K complexity.
* **No multi-tenant auth** — this is a prototype.
* **Reranker** is a no-op in mock mode (the mock LLM doesn't have
  meaningful relevance judgment).

---

## Compliance disclaimer

OpenFilingRAG is an **open-source technical prototype** for parsing and
querying public company disclosures. It is **not**:

* a stock-recommendation system
* a financial-advice service
* a price-prediction tool
* a substitute for professional investment advice

The system actively refuses requests for buy/sell/hold ratings, price
targets, and personalized portfolio advice. Generated reports include a
canonical disclaimer and link every claim to source evidence so readers
can verify and form their own conclusions.

---

## Roadmap

* Real SEC EDGAR fetcher (by CIK + accession number) with iXBRL parsing
* Cross-filing diff for `cross_year_comparison` (true YoY section diffing)
* LLM-judged eval harness with ground-truth questions per filing
* Optional reranker model (e.g. `bge-reranker-v2`) instead of LLM rerank
* Streaming `token` events from `generate_report` for live writing UI
* LangGraph Server deployment recipe + assistant-ui integration sample
* Document-level dedup across ingest of filing amendments

---

## Contributing

Bug reports, new retrieval intents, new data sources, and UI polish are all welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) — it covers dev setup, where to put new code, and the `make lint && make test` checks expected before opening a PR.

For questions and design discussion, prefer [GitHub Discussions](https://github.com/yybrother989/openfilingrag/discussions) over issues.

## License

Apache-2.0. See [LICENSE](LICENSE).
