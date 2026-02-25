"use client";
import { useState } from "react";
import type { InterruptPayload } from "@/lib/types";
export function SelectTarget({ interrupt, onSubmit }: { interrupt: InterruptPayload; onSubmit: (r: string) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const matches = interrupt.top_matches ?? [];
  return (
    <div className="space-y-4">
      <p className="text-sm font-medium text-amber-400">⟳ Select Chatflow to Update</p>
      <p className="text-sm text-muted-foreground">{interrupt.prompt}</p>
      {matches.length === 0 ? <p className="text-sm text-muted-foreground">No matching chatflows found.</p> : (
        <div className="space-y-2">
          {matches.map((m) => (
            <div key={m.id} role="button" tabIndex={0} onClick={() => setSelected(m.id)} onKeyDown={(e) => e.key === "Enter" && setSelected(m.id)}
              className={`cursor-pointer rounded-lg border p-3 ${selected === m.id ? "border-primary bg-primary/10" : "border-border hover:border-primary/50"}`}>
              <div className="flex items-start justify-between"><span className="font-medium text-sm">{m.name}</span>{selected === m.id && <span className="text-primary text-xs">✓</span>}</div>
              <div className="mt-1 font-mono text-xs text-muted-foreground">{m.id.slice(0, 16)}…</div>
            </div>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <button onClick={() => selected && onSubmit(selected)} disabled={!selected} className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50 hover:opacity-90">Update Selected Chatflow →</button>
        <button onClick={() => onSubmit("create new")} className="rounded border border-border px-4 py-2 text-sm hover:bg-muted">Create New Instead</button>
      </div>
    </div>
  );
}
