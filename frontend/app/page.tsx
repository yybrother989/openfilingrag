"use client";

import { useMemo } from "react";
import { Thread } from "@assistant-ui/react";

import { ConversationToolbar } from "@/components/ConversationToolbar";
import { ResearchInspector } from "@/components/ResearchInspector";
import { createResearchToolUIs } from "@/components/ResearchToolUIs";
import { ThemeToggle } from "@/components/ThemeToggle";
import { WorkspaceSidebar } from "@/components/WorkspaceSidebar";
import { useResearchAssistantRuntime } from "@/lib/assistantRuntime";
import { useConversations } from "@/lib/conversations";
import { useResearchWorkspace } from "@/lib/workspace";

export default function HomePage() {
  const workspace = useResearchWorkspace();
  const conv = useConversations();

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex items-center justify-between gap-6 border-b border-border bg-background/95 px-6 py-4">
        <div className="flex items-center gap-4">
          <img
            src="/chorus-logo-light.png"
            alt="Chorus AI"
            className="h-12 w-auto dark:hidden"
          />
          <img
            src="/chorus-logo-dark.png"
            alt="Chorus AI"
            className="hidden h-12 w-auto dark:block"
          />
          <div className="h-8 w-px bg-border" aria-hidden />
          <div className="flex flex-col leading-tight">
            <h1 className="text-base font-semibold tracking-tight">OpenFilingRAG</h1>
            <p className="text-[11px] text-muted-foreground">
              Filing-aware research workbench
            </p>
          </div>
        </div>
        <ThemeToggle />
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[288px_minmax(0,1fr)_360px]">
        <div className="min-h-0">
          <WorkspaceSidebar
            controls={workspace.controls}
            setControls={workspace.setControls}
            documents={workspace.documents}
            localFiles={workspace.localFiles}
            activeDocumentIds={workspace.activeDocumentIds}
            busy={workspace.busy}
            notice={workspace.notice}
            indexedPathSet={workspace.indexedPathSet}
            onToggleDocument={workspace.toggleDocument}
            onSetSelection={workspace.setSelection}
            onClearSelection={workspace.clearSelection}
            onInspectDocument={workspace.inspectDocument}
            onImportLocalFile={workspace.importLocalFile}
            onReindexDocument={workspace.reindexDocument}
            onDeleteDocument={workspace.deleteDocument}
            onRefresh={workspace.refreshWorkspace}
            onPreviewEdgar={workspace.previewEdgar}
            onPullEdgar={workspace.pullEdgar}
            edgarPreview={workspace.edgarPreview}
          />
        </div>

        {/* `key={conversationId}` here remounts the entire workbench
            (chat + inspector) when the user switches conversations, so
            the runtime tears down — aborting any in-flight stream — and
            rebuilds with the new history. The fragment lets both
            columns sit directly under the page-level CSS grid. */}
        {conv.hydrated ? (
          <Workbench
            key={conv.currentId}
            conversationId={conv.currentId}
            workspace={workspace}
            conversations={conv.conversations}
            onNewConversation={conv.newConversation}
            onSwitchConversation={conv.switchTo}
            onDeleteConversation={conv.deleteConversation}
            onTouchConversation={conv.touchConversation}
          />
        ) : (
          <>
            <section className="min-h-0 bg-background" />
            <div className="min-h-0" />
          </>
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------
// Workbench — owns the chat runtime and renders both the center chat
// column and the right-side inspector. Returns a fragment so its two
// children land in the parent's CSS grid as direct siblings.
// ---------------------------------------------------------------------
type WorkspaceShape = ReturnType<typeof useResearchWorkspace>;

function Workbench({
  conversationId,
  workspace,
  conversations,
  onNewConversation,
  onSwitchConversation,
  onDeleteConversation,
  onTouchConversation,
}: {
  conversationId: string;
  workspace: WorkspaceShape;
  conversations: ReturnType<typeof useConversations>["conversations"];
  onNewConversation: () => void;
  onSwitchConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onTouchConversation: (id: string, candidateTitle?: string) => void;
}) {
  const runtime = useResearchAssistantRuntime({
    conversationId,
    controls: workspace.controls,
    documentIds: workspace.activeDocumentIds,
    onAttachmentIngested: workspace.afterIngestion,
    onUserMessage: (prompt) => onTouchConversation(conversationId, prompt),
  });

  const tools = useMemo(
    () =>
      createResearchToolUIs({
        onSelectEvidence: runtime.setSelectedEvidenceId,
        selectedEvidenceId: runtime.selectedEvidenceId,
      }),
    [runtime.selectedEvidenceId],
  );

  return (
    <>
      <section className="relative min-h-0 bg-background">
        {/* Conversation toolbar floats top-right of the chat column. */}
        <div className="absolute right-4 top-3 z-20 rounded-md border border-border/60 bg-background/90 p-0.5 shadow-sm backdrop-blur">
          <ConversationToolbar
            conversations={conversations}
            currentId={conversationId}
            onNew={onNewConversation}
            onSwitch={onSwitchConversation}
            onDelete={onDeleteConversation}
          />
        </div>

        <div className="assistant-shell mx-auto h-full max-w-[920px]">
          <Thread
            runtime={runtime.runtime}
            tools={tools}
            assistantAvatar={{ fallback: "OF" }}
            welcome={{
              message:
                "Ask a filing question, attach a local document, or scope the run to selected indexed filings.",
              suggestions: workspace.sampleQuestions.map((question) => ({
                prompt: question.text,
                text: question.text,
              })),
            }}
            composer={{ allowAttachments: true }}
            assistantMessage={{ allowCopy: true, allowReload: true }}
            strings={{
              composer: {
                input: {
                  placeholder:
                    "Ask about risks, margins, liquidity, or attach a filing to index before querying.",
                },
              },
            }}
          />
        </div>

        {runtime.error ? (
          <div className="absolute inset-x-0 bottom-0 border-t border-destructive/30 bg-destructive/10 px-6 py-2 text-xs text-destructive">
            {runtime.error}
          </div>
        ) : null}
      </section>

      <div className="min-h-0">
        <ResearchInspector
          evidence={runtime.evidence}
          inspectedDocument={workspace.inspectedDocument}
          selectedEvidenceId={runtime.selectedEvidenceId}
          onSelectEvidence={runtime.setSelectedEvidenceId}
          status={runtime.status}
        />
      </div>
    </>
  );
}
