"use client";
import { useState } from "react";
import { useSessionStore } from "@/store/session-store";
import { api } from "@/lib/api";
import { StreamingPanel } from "./StreamingPanel";
import { Clarification } from "./Clarification";
import { CredentialCheck } from "./CredentialCheck";
import { PlanApproval } from "./PlanApproval";
import { SelectTarget } from "./SelectTarget";
import { ResultReview } from "./ResultReview";

function formatDuration(ms: number): string {
  if (ms >= 60000) return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function CompletedState({ onNewSession }: { onNewSession: () => void }) {
  const active = useSessionStore((s) => s.active);
  const [showAudit, setShowAudit] = useState(false);
  const [auditText, setAuditText] = useState<string | null>(null);
  const [loadingAudit, setLoadingAudit] = useState(false);

  if (!active) return null;

  const totalTokens = active.total_input_tokens + active.total_output_tokens;
  const totalDurationMs = active.phases
    .flatMap((p) => p.nodes)
    .reduce((sum, n) => sum + (n.duration_ms ?? 0), 0);

  async function toggleAudit() {
    if (showAudit) { setShowAudit(false); return; }
    if (auditText !== null) { setShowAudit(true); return; }
    setLoadingAudit(true);
    try {
      const res = await api.getSessionSummary(active!.id);
      setAuditText(res.summary);
      setShowAudit(true);
    } catch {
      setAuditText("Failed to load audit trail.");
      setShowAudit(true);
    } finally {
      setLoadingAudit(false);
    }
  }

  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
      <div className="text-5xl text-green-400">✓</div>
      <h2 className="text-lg font-semibold text-green-400">Built Successfully</h2>
      {active.chatflow_id && (
        <p className="font-mono text-xs text-muted-foreground">Chatflow: {active.chatflow_id}</p>
      )}
      <div className="flex gap-4 text-xs text-muted-foreground">
        <span>iter {active.iteration}</span>
        {totalTokens > 0 && <span>{totalTokens.toLocaleString()} tok</span>}
        {totalDurationMs > 0 && <span>{formatDuration(totalDurationMs)}</span>}
      </div>
      <button
        onClick={toggleAudit}
        disabled={loadingAudit}
        className="text-xs text-muted-foreground underline hover:text-foreground disabled:opacity-50"
      >
        {loadingAudit ? "Loading…" : showAudit ? "Hide Audit Trail" : "View Audit Trail"}
      </button>
      {showAudit && auditText && (
        <pre className="mt-1 max-h-60 w-full max-w-2xl overflow-auto rounded-md bg-muted p-3 text-left font-mono text-xs text-muted-foreground">
          {auditText}
        </pre>
      )}
      <button
        onClick={onNewSession}
        className="mt-4 rounded bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
      >
        + New Session
      </button>
    </div>
  );
}

function ErrorState({ detail }: { detail: string | null }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
      <div className="text-4xl text-destructive">✗</div>
      <h2 className="text-base font-semibold text-destructive">Session Error</h2>
      <p className="max-w-sm text-xs text-muted-foreground">{detail ?? "An unexpected error occurred."}</p>
    </div>
  );
}

function InitialState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-20 text-center">
      <p className="text-sm text-muted-foreground">Starting session…</p>
    </div>
  );
}

export function ActivePanel({ onSubmit }: { onSubmit: (response: string) => void }) {
  const { active, setModalOpen } = useSessionStore((s) => ({ active: s.active, setModalOpen: s.setModalOpen }));

  if (!active) return <InitialState />;

  if (active.status === "streaming") return <StreamingPanel />;

  if (active.status === "completed") {
    return <CompletedState onNewSession={() => setModalOpen(true)} />;
  }

  if (active.status === "error") {
    return <ErrorState detail={active.errorDetail} />;
  }

  if (active.status === "pending_interrupt" && active.interrupt) {
    const { interrupt } = active;
    switch (interrupt.type) {
      case "clarification":
        return <Clarification interrupt={interrupt} onSubmit={onSubmit} />;
      case "credential_check":
        return <CredentialCheck interrupt={interrupt} onSubmit={onSubmit} />;
      case "plan_approval":
        return <PlanApproval interrupt={interrupt} onSubmit={onSubmit} />;
      case "select_target":
        return <SelectTarget interrupt={interrupt} onSubmit={onSubmit} />;
      case "result_review":
        return <ResultReview interrupt={interrupt} onSubmit={onSubmit} />;
      default:
        return (
          <div className="p-6 text-sm text-muted-foreground">
            Unknown interrupt type: <code className="font-mono">{(interrupt as { type: string }).type}</code>
          </div>
        );
    }
  }

  return <InitialState />;
}
