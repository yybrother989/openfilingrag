export type EventType =
  | "run_started"
  | "node_start"
  | "node_end"
  | "query_classified"
  | "retrieval_plan"
  | "section_selected"
  | "evidence_found"
  | "verification_warning"
  | "token"
  | "report_section"
  | "final_report"
  | "run_completed"
  | "error";

export interface AgentEvent<T = Record<string, unknown>> {
  event_id: string;
  run_id: string;
  thread_id?: string | null;
  timestamp: string;
  type: EventType;
  node?: string | null;
  payload: T;
}

export interface EvidenceItem {
  source_id: string;
  document_id: number;
  chunk_index: number;
  ticker: string;
  company_name?: string | null;
  document_type: string;
  fiscal_year?: number | null;
  filing_date?: string | null;
  source_priority: string;
  section: string;
  subsection?: string | null;
  content_type: string;
  page_start?: number | null;
  page_end?: number | null;
  text: string;
  metric_tags: string[];
  risk_tags: string[];
  relevance_score: number;
  retrieval_reason?: string | null;
  score_breakdown?: Record<string, number> | null;
  extra?: Record<string, unknown> | null;
  snippet?: string | null;
}

export interface Finding {
  claim: string;
  evidence_ids: string[];
  confidence: "high" | "medium" | "low";
  reasoning_summary?: string | null;
}

export interface FinancialMetric {
  metric_name: string;
  period?: string | null;
  value?: string | null;
  change?: string | null;
  source_evidence_ids: string[];
}

export interface RiskFactor {
  risk: string;
  category?: string | null;
  materiality: "high" | "medium" | "low" | "unknown";
  evidence_ids: string[];
}

export interface ManagementCommentary {
  topic: string;
  quote_or_paraphrase: string;
  evidence_ids: string[];
}

export interface ResearchReport {
  report_id: string;
  query: string;
  ticker?: string | null;
  company_name?: string | null;
  intent: string;
  summary: string;
  key_findings: Finding[];
  financial_metrics: FinancialMetric[];
  risk_factors: RiskFactor[];
  management_commentary: ManagementCommentary[];
  evidence: EvidenceItem[];
  limitations: string[];
  validation_warnings: string[];
  no_advice_disclaimer: string;
  generated_at: string;
}

export type RunStatus = "idle" | "streaming" | "completed" | "failed";

export interface ResearchControls {
  ticker: string;
  company_name: string;
}

export interface ScopedResearchRequest {
  query: string;
  ticker?: string;
  company_name?: string;
  document_ids: number[];
}

export interface DocumentOut {
  id: number;
  ticker: string;
  company_name: string;
  document_type: string;
  fiscal_year?: number | null;
  filing_date?: string | null;
  source_url?: string | null;
  source_priority: string;
  page_count?: number | null;
  sections_count?: number | null;
  chunks_count?: number | null;
  tables_count?: number | null;
  raw_path?: string | null;
  created_at?: string | null;
}

export interface SectionOut {
  id: number;
  document_id: number;
  canonical_name: string;
  raw_heading?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  char_start: number;
  char_end: number;
}

export interface DocumentDetailResponse {
  document: DocumentOut;
  sections: SectionOut[];
}

export interface LocalFileEntry {
  name: string;
  relative_path: string;
  local_path: string;
  kind: "file" | "directory";
  extension?: string | null;
  size_bytes?: number | null;
  modified_at: string;
}

export interface IngestionResult {
  document_id: number;
  ticker: string;
  company_name: string;
  document_type: string;
  sections_count: number;
  chunks_count: number;
  tables_count: number;
  status: string;
  warnings: string[];
}

export interface EdgarFilingRef {
  ticker: string;
  accession_number: string;
  form: string;
  filing_date: string;
  archive_url: string;
  primary_document: string;
  description?: string | null;
  fiscal_year?: number | null;
}

export interface EdgarFilingsResponse {
  ticker: string;
  cik?: number | null;
  count: number;
  filings: EdgarFilingRef[];
}

export interface EdgarPullResponse {
  ticker: string;
  cik?: number | null;
  listed: number;
  downloaded: number;
  ingested: number;
  skipped_existing: number;
  failures: number;
  results: IngestionResult[];
}

export interface ToolCardPayloads {
  query_classified: {
    intent: string;
    ticker?: string | null;
    company_name?: string | null;
    fiscal_year?: number | null;
    wants_cross_year?: boolean;
    document_ids?: number[];
    refused?: boolean;
    reason?: string;
    message?: string;
  };
  retrieval_plan: {
    intent: string;
    document_ids?: number[];
    preferred_sections: string[];
    preferred_document_types: string[];
    preferred_content_types?: string[];
    metric_expansions: string[];
    risk_expansions: string[];
    cross_year?: boolean;
    table_priority?: boolean;
    top_k?: number;
  };
  section_selected: {
    sections: string[];
  };
  retrieve_evidence: {
    items: EvidenceItem[];
  };
  verification_warning: {
    warnings: string[];
  };
  final_report: ResearchReport;
}
