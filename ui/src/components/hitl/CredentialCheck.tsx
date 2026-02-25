"use client";
import { useState } from "react";
import type { InterruptPayload } from "@/lib/types";
export function CredentialCheck({ interrupt, onSubmit }: { interrupt: InterruptPayload; onSubmit: (r: string) => void }) {
  const [ids, setIds] = useState("");
  return (
    <div className="space-y-4">
      <p className="text-sm font-medium text-red-400">⚠ Credential Check</p>
      <div className="flex flex-wrap gap-2">{(interrupt.missing_credentials ?? []).map((c) => <span key={c} className="rounded bg-red-400/10 px-2 py-0.5 text-xs text-red-400">{c}</span>)}</div>
      <p className="text-xs text-muted-foreground">Create in Flowise → Settings → Credentials → Add New, then paste IDs below. Or reply <code>skip</code>.</p>
      <textarea autoFocus className="w-full resize-none rounded-md border border-border bg-muted px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" rows={3} placeholder="Credential IDs or 'skip'" value={ids} onChange={(e) => setIds(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), onSubmit(ids))} />
      <button onClick={() => onSubmit(ids)} className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">Submit Credentials →</button>
    </div>
  );
}
