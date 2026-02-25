"use client";
import { useState } from "react";
import type { InterruptPayload } from "@/lib/types";
export function PlanApproval({ interrupt, onSubmit }: { interrupt: InterruptPayload; onSubmit: (r: string) => void }) {
  const [feedback, setFeedback] = useState("");
  const [approach, setApproach] = useState<string | null>(null);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-green-400">✎ Plan Ready for Review</span>
        {interrupt.pattern_used && interrupt.pattern_id != null && <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">Pattern: {interrupt.pattern_id}</span>}
      </div>
      <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 font-mono text-xs">{interrupt.plan ?? "(no plan)"}</pre>
      {interrupt.options && interrupt.options.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">Select an approach:</p>
          <div className="flex flex-wrap gap-2">
            {interrupt.options.map((opt) => (
              <button key={opt} onClick={() => setApproach(opt)}
                className={`rounded border px-3 py-1 text-xs ${approach === opt ? "border-primary bg-primary/20 text-primary" : "border-border text-muted-foreground hover:border-primary/50"}`}>{opt}</button>
            ))}
          </div>
        </div>
      )}
      <textarea autoFocus className="w-full resize-none rounded-md border border-border bg-muted px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" rows={3} placeholder="approved" value={feedback} onChange={(e) => setFeedback(e.target.value)} />
      <div className="flex gap-2">
        <button onClick={() => onSubmit(approach ? `approved - approach: ${approach}` : "approved")} disabled={!!(interrupt.options && !approach)}
          className="rounded bg-green-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 hover:bg-green-500">✓ Approve Plan</button>
        {feedback && <button onClick={() => onSubmit(feedback)} className="rounded border border-border px-4 py-2 text-sm hover:bg-muted">Send Changes →</button>}
      </div>
    </div>
  );
}
