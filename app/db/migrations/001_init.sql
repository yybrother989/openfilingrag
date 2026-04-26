-- =====================================================================
-- OpenFilingRAG schema — initial migration
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------- companies ------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(16)  NOT NULL UNIQUE,
    name            VARCHAR(512) NOT NULL,
    sector          VARCHAR(128),
    industry        VARCHAR(256),
    extra           JSONB,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_companies_ticker ON companies (ticker);

-- ---------- documents ------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    ticker          VARCHAR(16)  NOT NULL,
    company_name    VARCHAR(512) NOT NULL,
    document_type   VARCHAR(64)  NOT NULL,
    fiscal_year     INTEGER,
    filing_date     DATE,
    source_url      TEXT,
    source_priority VARCHAR(64)  NOT NULL DEFAULT 'primary_filing',
    page_count      INTEGER,
    raw_path        TEXT,
    extra           JSONB,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_documents_ticker          ON documents (ticker);
CREATE INDEX IF NOT EXISTS ix_documents_document_type   ON documents (document_type);
CREATE INDEX IF NOT EXISTS ix_documents_fiscal_year     ON documents (fiscal_year);
CREATE INDEX IF NOT EXISTS ix_documents_source_priority ON documents (source_priority);

-- ---------- document_sections ---------------------------------------
CREATE TABLE IF NOT EXISTS document_sections (
    id              SERIAL PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    canonical_name  VARCHAR(128) NOT NULL,
    raw_heading     TEXT,
    page_start      INTEGER,
    page_end        INTEGER,
    char_start      INTEGER NOT NULL,
    char_end        INTEGER NOT NULL,
    ordinal         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_sections_document  ON document_sections (document_id);
CREATE INDEX IF NOT EXISTS ix_sections_canonical ON document_sections (canonical_name);

-- ---------- document_chunks (with embedding) ------------------------
CREATE TABLE IF NOT EXISTS document_chunks (
    id              SERIAL PRIMARY KEY,
    source_id       UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id      INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,

    ticker          VARCHAR(16)  NOT NULL,
    company_name    VARCHAR(512) NOT NULL,
    document_type   VARCHAR(64)  NOT NULL,
    fiscal_year     INTEGER,
    filing_date     DATE,
    source_priority VARCHAR(64)  NOT NULL DEFAULT 'primary_filing',

    section         VARCHAR(128) NOT NULL,
    subsection      VARCHAR(256),
    content_type    VARCHAR(64)  NOT NULL DEFAULT 'paragraph',

    page_start      INTEGER,
    page_end        INTEGER,
    chunk_index     INTEGER NOT NULL DEFAULT 0,

    chunk_text      TEXT NOT NULL,
    metric_tags     TEXT[] DEFAULT '{}',
    risk_tags       TEXT[] DEFAULT '{}',

    embedding       vector(1536),
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(chunk_text, ''))) STORED,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_chunks_document        ON document_chunks (document_id);
CREATE INDEX IF NOT EXISTS ix_chunks_ticker          ON document_chunks (ticker);
CREATE INDEX IF NOT EXISTS ix_chunks_document_type   ON document_chunks (document_type);
CREATE INDEX IF NOT EXISTS ix_chunks_fiscal_year     ON document_chunks (fiscal_year);
CREATE INDEX IF NOT EXISTS ix_chunks_section         ON document_chunks (section);
CREATE INDEX IF NOT EXISTS ix_chunks_content_type    ON document_chunks (content_type);
CREATE INDEX IF NOT EXISTS ix_chunks_source_priority ON document_chunks (source_priority);
CREATE INDEX IF NOT EXISTS ix_chunks_metric_tags     ON document_chunks USING GIN (metric_tags);
CREATE INDEX IF NOT EXISTS ix_chunks_risk_tags       ON document_chunks USING GIN (risk_tags);
CREATE INDEX IF NOT EXISTS ix_chunks_tsv             ON document_chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS ix_chunks_embedding       ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ---------- financial_tables ----------------------------------------
CREATE TABLE IF NOT EXISTS financial_tables (
    id                 SERIAL PRIMARY KEY,
    document_id        INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_canonical  VARCHAR(128),
    page               INTEGER,
    caption            TEXT,
    rows               JSONB NOT NULL,
    extra              JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_tables_document ON financial_tables (document_id);

-- ---------- research_reports + evidence_items -----------------------
CREATE TABLE IF NOT EXISTS research_reports (
    id              SERIAL PRIMARY KEY,
    report_id       UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    query           TEXT NOT NULL,
    ticker          VARCHAR(16),
    company_name    VARCHAR(512),
    intent          VARCHAR(64),
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_reports_ticker ON research_reports (ticker);
CREATE INDEX IF NOT EXISTS ix_reports_intent ON research_reports (intent);

-- evidence_items is a denormalized cache so /evidence/{source_id}
-- can return the snippet exactly as the report cited it.
CREATE TABLE IF NOT EXISTS evidence_items (
    id              SERIAL PRIMARY KEY,
    source_id       UUID NOT NULL,
    report_id       UUID REFERENCES research_reports(report_id) ON DELETE CASCADE,
    chunk_id        INTEGER REFERENCES document_chunks(id) ON DELETE CASCADE,
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_evidence_source_id ON evidence_items (source_id);
CREATE INDEX IF NOT EXISTS ix_evidence_report_id ON evidence_items (report_id);
