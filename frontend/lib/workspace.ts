"use client";

import { useEffect, useState } from "react";

import {
  deleteDocument as apiDeleteDocument,
  getDocument,
  getSampleQuestions,
  ingestLocalFile,
  listDocuments,
  listLocalFiles,
  previewEdgarFilings,
  pullEdgarFilings,
  reindexDocument as apiReindexDocument,
} from "./api";
import type {
  DocumentDetailResponse,
  DocumentOut,
  EdgarFilingsResponse,
  EdgarPullResponse,
  IngestionResult,
  LocalFileEntry,
  ResearchControls,
} from "./types";

const STORAGE_KEY = "openfilingrag.workspace.v1";

interface PersistedWorkspace {
  controls: ResearchControls;
  activeDocumentIds: number[];
}

const DEFAULT_CONTROLS: ResearchControls = {
  ticker: "AAPL",
  company_name: "",
};

export function useResearchWorkspace() {
  const [controls, setControls] = useState<ResearchControls>(DEFAULT_CONTROLS);
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [localFiles, setLocalFiles] = useState<LocalFileEntry[]>([]);
  const [activeDocumentIds, setActiveDocumentIds] = useState<number[]>([]);
  const [inspectedDocument, setInspectedDocument] =
    useState<DocumentDetailResponse | null>(null);
  const [sampleQuestions, setSampleQuestions] = useState<
    { intent: string; text: string }[]
  >([]);
  const [edgarPreview, setEdgarPreview] = useState<EdgarFilingsResponse | null>(null);
  const [edgarResult, setEdgarResult] = useState<EdgarPullResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as PersistedWorkspace;
      if (parsed.controls) setControls({ ...DEFAULT_CONTROLS, ...parsed.controls });
      if (Array.isArray(parsed.activeDocumentIds)) {
        setActiveDocumentIds(parsed.activeDocumentIds);
      }
    } catch {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    const persisted: PersistedWorkspace = {
      controls,
      activeDocumentIds,
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
  }, [controls, activeDocumentIds]);

  const refreshWorkspace = async () => {
    setBusy("refresh");
    try {
      const [docs, files, samples] = await Promise.all([
        listDocuments(),
        listLocalFiles(),
        getSampleQuestions(),
      ]);
      setDocuments(docs);
      setLocalFiles(files);
      setSampleQuestions(samples.questions);
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    refreshWorkspace().catch((error: Error) => setNotice(error.message));
  }, []);

  const toggleDocument = (documentId: number) => {
    setActiveDocumentIds((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId].sort((a, b) => a - b),
    );
  };

  const clearSelection = () => setActiveDocumentIds([]);

  const setSelection = (ids: number[]) => {
    const sorted = Array.from(new Set(ids)).sort((a, b) => a - b);
    setActiveDocumentIds(sorted);
  };

  const deleteDocument = async (documentId: number) => {
    setBusy(`delete:${documentId}`);
    try {
      await apiDeleteDocument(documentId);
      setActiveDocumentIds((current) => current.filter((id) => id !== documentId));
      setInspectedDocument((current) =>
        current?.document.id === documentId ? null : current,
      );
      setNotice(`Removed document ${documentId} from the corpus.`);
      await refreshWorkspace();
    } catch (err) {
      setNotice(
        err instanceof Error
          ? `Delete failed: ${err.message}`
          : "Delete failed",
      );
    } finally {
      setBusy(null);
    }
  };

  const reindexDocument = async (documentId: number) => {
    setBusy(`reindex:${documentId}`);
    try {
      const result = await apiReindexDocument(documentId);
      setNotice(
        `Re-indexed ${result.ticker} ${result.document_type} as document ${result.document_id}.`,
      );
      // The new document gets a fresh id; remap selection if the user had
      // the old one selected.
      setActiveDocumentIds((current) =>
        current.includes(documentId)
          ? Array.from(new Set([...current.filter((id) => id !== documentId), result.document_id])).sort(
              (a, b) => a - b,
            )
          : current,
      );
      await refreshWorkspace();
      await inspectDocument(result.document_id);
    } catch (err) {
      setNotice(
        err instanceof Error
          ? `Re-index failed: ${err.message}`
          : "Re-index failed",
      );
    } finally {
      setBusy(null);
    }
  };

  const inspectDocument = async (documentId: number) => {
    setBusy(`document:${documentId}`);
    try {
      const detail = await getDocument(documentId);
      setInspectedDocument(detail);
    } finally {
      setBusy(null);
    }
  };

  const importLocalFile = async (localPath: string) => {
    setBusy(`import:${localPath}`);
    try {
      const result = await ingestLocalFile({
        ticker: controls.ticker,
        company_name: controls.company_name || controls.ticker || "Local Filing",
        document_type: "10-K",
        local_path: localPath,
      });
      await afterIngestion(result);
      return result;
    } finally {
      setBusy(null);
    }
  };

  const afterIngestion = async (result: IngestionResult) => {
    setNotice(`Indexed document ${result.document_id} for ${result.ticker}.`);
    await refreshWorkspace();
    setActiveDocumentIds((current) =>
      current.includes(result.document_id)
        ? current
        : [...current, result.document_id].sort((a, b) => a - b),
    );
    await inspectDocument(result.document_id);
  };

  const previewEdgar = async (ticker: string, types: string, limit: number) => {
    setBusy("edgar-preview");
    try {
      const preview = await previewEdgarFilings({ ticker, types, limit });
      setEdgarPreview(preview);
      setNotice(`Previewed ${preview.count} filing(s) for ${preview.ticker}.`);
      return preview;
    } finally {
      setBusy(null);
    }
  };

  const pullEdgar = async (ticker: string, types: string[], limit: number) => {
    setBusy("edgar-pull");
    try {
      const result = await pullEdgarFilings({
        ticker,
        types,
        limit,
        company_name: controls.company_name,
      });
      setEdgarResult(result);
      setNotice(
        `Pulled ${result.downloaded} filing(s); indexed ${result.ingested} and skipped ${result.skipped_existing}.`,
      );
      await refreshWorkspace();
      return result;
    } finally {
      setBusy(null);
    }
  };

  const indexedPathSet = new Set(
    documents
      .map((document) => document.raw_path)
      .filter((value): value is string => Boolean(value)),
  );

  return {
    controls,
    setControls,
    documents,
    localFiles,
    activeDocumentIds,
    busy,
    notice,
    sampleQuestions,
    inspectedDocument,
    edgarPreview,
    edgarResult,
    indexedPathSet,
    refreshWorkspace,
    toggleDocument,
    clearSelection,
    setSelection,
    deleteDocument,
    reindexDocument,
    inspectDocument,
    importLocalFile,
    afterIngestion,
    previewEdgar,
    pullEdgar,
    setNotice,
  };
}
