"use client";
import { useSessionStore } from "@/store/session-store";
import { StreamingPanel } from "./StreamingPanel";
import { Clarification } from "./Clarification";
import { CredentialCheck } from "./CredentialCheck";
import { PlanApproval } from "./PlanApproval";
import { SelectTarget } from "./SelectTarget";
import { ResultReview } from "./ResultReview";

function CompletedState({ chatflowId, onNewSession }: { chatflowId: string | null; onNewSession: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
      <div className="text-5xl text-green-400">✓</div>
      <h2 className="text-lg font-semibold text-green-400">Built Successfully</h2>
      {chatflowId && (
        <p className="font-mono text-xs text-muted-foreground">Chatflow: {chatflowId}</p>
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
    return <CompletedState chatflowId={active.chatflow_id} onNewSession={() => setModalOpen(true)} />;
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
