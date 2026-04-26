-- =====================================================================
-- 002 — Switch retrieval store to langchain_postgres.PGVector
-- =====================================================================
-- Run order:
--   1. data migration script (--dry-run first) creates the PGVector
--      tables and validates row counts:
--         python scripts/migrate_chunks_to_pgvector.py --dry-run
--   2. PART A   — additive changes (indexes, drop FK).
--   3. data migration for real:
--         python scripts/migrate_chunks_to_pgvector.py
--   4. verify counts:
--        SELECT count(*) FROM document_chunks;       -- old
--        SELECT count(*) FROM langchain_pg_embedding;-- new (>= old)
--   5. PART B   — destructive (drops document_chunks). Only after verify.
-- =====================================================================

-- ---------------------------------------------------------------------
-- PART A — additive
-- ---------------------------------------------------------------------

-- Generated tsvector column on langchain_pg_embedding.document so
-- PGFTSRetriever can run plainto_tsquery + ts_rank_cd. Mirrors the
-- column that used to live on document_chunks.tsv.
ALTER TABLE langchain_pg_embedding
  ADD COLUMN IF NOT EXISTS tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', coalesce(document, ''))) STORED;

CREATE INDEX IF NOT EXISTS ix_lc_emb_tsv
  ON langchain_pg_embedding USING GIN (tsv);

-- GIN over the cmetadata JSONB so per-field filters (ticker, section,
-- fiscal_year, document_type) hit an index. jsonb_path_ops is cheaper
-- than the default jsonb_ops and supports our @> containment queries.
CREATE INDEX IF NOT EXISTS ix_lc_emb_cmetadata
  ON langchain_pg_embedding USING GIN (cmetadata jsonb_path_ops);

-- ivfflat on the embedding column (cosine). PGVector will create one
-- automatically on first use, but with HNSW in newer releases — this
-- ensures we keep ivfflat with lists=100 to match 001 semantics.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
     WHERE indexname = 'ix_lc_emb_embedding'
       AND tablename  = 'langchain_pg_embedding'
  ) THEN
    EXECUTE 'CREATE INDEX ix_lc_emb_embedding
              ON langchain_pg_embedding
              USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)';
  END IF;
END$$;

-- evidence_items.chunk_id used to FK into document_chunks. After Phase 2
-- evidence is keyed by source_id (UUID stable across ingest runs), so
-- the chunk_id column is dead weight. Drop the column outright.
ALTER TABLE evidence_items DROP CONSTRAINT IF EXISTS evidence_items_chunk_id_fkey;
ALTER TABLE evidence_items DROP COLUMN IF EXISTS chunk_id;


-- ---------------------------------------------------------------------
-- PART B — destructive (run only after verifying migration counts)
-- ---------------------------------------------------------------------
-- Uncomment the block below once `langchain_pg_embedding` has at least
-- as many rows as the old `document_chunks` table.

-- DROP INDEX IF EXISTS ix_chunks_embedding;
-- DROP INDEX IF EXISTS ix_chunks_tsv;
-- DROP INDEX IF EXISTS ix_chunks_metric_tags;
-- DROP INDEX IF EXISTS ix_chunks_risk_tags;
-- DROP TABLE IF EXISTS document_chunks;
