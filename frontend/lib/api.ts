import type {
  DocumentDetailResponse,
  DocumentOut,
  EdgarFilingsResponse,
  EdgarPullResponse,
  IngestionResult,
  LocalFileEntry,
} from "./types";

// Hit the backend directly. Next.js dev rewrites for SSE (chunked
// transfer through webpack-dev middleware) drop the body stream after
// the first chunk in some Next 15 setups, surfacing as a browser
// "network error" mid-stream. Backend has CORS open for localhost:3000.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function fetchVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `HTTP ${response.status}`);
  }
}

export function getSampleQuestions() {
  return fetchJson<{ questions: { intent: string; text: string }[] }>(
    "/research/sample_questions",
  );
}

export function listDocuments() {
  return fetchJson<DocumentOut[]>("/documents");
}

export function getDocument(documentId: number) {
  return fetchJson<DocumentDetailResponse>(`/documents/${documentId}`);
}

export function listLocalFiles() {
  return fetchJson<LocalFileEntry[]>("/documents/local-files");
}

export function deleteDocument(documentId: number) {
  return fetchVoid(`/documents/${documentId}`, { method: "DELETE" });
}

export function reindexDocument(documentId: number) {
  return fetchJson<IngestionResult>(`/documents/${documentId}/reindex`, {
    method: "POST",
  });
}

export async function ingestLocalFile(input: {
  ticker: string;
  company_name: string;
  document_type: string;
  fiscal_year?: number | null;
  filing_date?: string | null;
  local_path: string;
  source_priority?: string;
}) {
  const form = new FormData();
  form.set("ticker", input.ticker);
  form.set("company_name", input.company_name);
  form.set("document_type", input.document_type);
  form.set("local_path", input.local_path);
  form.set("source_priority", input.source_priority || "primary_filing");
  if (input.fiscal_year) form.set("fiscal_year", String(input.fiscal_year));
  if (input.filing_date) form.set("filing_date", input.filing_date);
  return fetchJson<IngestionResult>("/documents/ingest", {
    method: "POST",
    body: form,
  });
}

export async function ingestUploadFile(input: {
  ticker: string;
  company_name: string;
  document_type: string;
  fiscal_year?: number | null;
  filing_date?: string | null;
  file: File;
  source_priority?: string;
}) {
  const form = new FormData();
  form.set("ticker", input.ticker);
  form.set("company_name", input.company_name);
  form.set("document_type", input.document_type);
  form.set("file", input.file);
  form.set("source_priority", input.source_priority || "primary_filing");
  if (input.fiscal_year) form.set("fiscal_year", String(input.fiscal_year));
  if (input.filing_date) form.set("filing_date", input.filing_date);
  return fetchJson<IngestionResult>("/documents/ingest", {
    method: "POST",
    body: form,
  });
}

export function previewEdgarFilings(input: {
  ticker: string;
  types: string;
  limit: number;
}) {
  const params = new URLSearchParams({
    types: input.types,
    limit: String(input.limit),
  });
  return fetchJson<EdgarFilingsResponse>(
    `/sources/edgar/filings/${input.ticker.toUpperCase()}?${params.toString()}`,
  );
}

export function pullEdgarFilings(input: {
  ticker: string;
  types: string[];
  limit: number;
  company_name?: string;
}) {
  return fetchJson<EdgarPullResponse>("/sources/edgar/pull", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ticker: input.ticker.toUpperCase(),
      types: input.types,
      limit: input.limit,
      company_name: input.company_name || undefined,
    }),
  });
}

export { API_BASE };
