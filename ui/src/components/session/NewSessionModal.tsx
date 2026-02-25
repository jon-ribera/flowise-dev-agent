"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { openNewSessionStream } from "@/lib/sse";
import { useSessionStore } from "@/store/session-store";

export function NewSessionModal({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const { initActive, applySSEEvent } = useSessionStore();
  const [requirement, setRequirement] = useState("");
  const [testTrials, setTestTrials] = useState(1);
  const [submitting, setSubmitting] = useState(false);

  function handleSubmit() {
    if (!requirement.trim()) return;
    setSubmitting(true);
    const threadId = crypto.randomUUID();
    initActive(threadId);
    onClose();
    router.push(`/sessions/${threadId}`);
    openNewSessionStream({ requirement: requirement.trim(), thread_id: threadId, test_trials: testTrials }, applySSEEvent, (err) => console.error("SSE error", err));
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-lg rounded-xl border border-border bg-background p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold">New Session</h2>
        <label className="mb-1 block text-sm text-muted-foreground">Requirement</label>
        <textarea autoFocus className="mb-4 w-full resize-none rounded-md border border-border bg-muted px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" style={{ minHeight: 120 }}
          placeholder="Describe what you want to build or change in Flowise..."
          value={requirement} onChange={(e) => setRequirement(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) handleSubmit(); }} />
        <label className="mb-1 block text-sm text-muted-foreground">Test trials (1–5)</label>
        <input type="number" min={1} max={5} value={testTrials} onChange={(e) => setTestTrials(Number(e.target.value))}
          className="mb-1 w-24 rounded-md border border-border bg-muted px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
        <p className="mb-4 text-xs text-muted-foreground">Higher values = pass^k reliability.</p>
        {/* TODO: Advanced section */}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded px-4 py-2 text-sm text-muted-foreground hover:text-foreground">Cancel</button>
          <button onClick={handleSubmit} disabled={!requirement.trim() || submitting}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50 hover:opacity-90">
            {submitting ? "Starting…" : "Start Session →"}
          </button>
        </div>
      </div>
    </div>
  );
}
