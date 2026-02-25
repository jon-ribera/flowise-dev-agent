"use client";
import { useState } from "react";
import type { InterruptPayload } from "@/lib/types";
export function Clarification({ interrupt, onSubmit }: { interrupt: InterruptPayload; onSubmit: (r: string) => void }) {
  const [answer, setAnswer] = useState("");
  return (
    <div className="space-y-4">
      <p className="text-sm font-medium text-blue-400">? Clarification Needed</p>
      <p className="text-sm">{interrupt.prompt}</p>
      <textarea autoFocus className="w-full resize-none rounded-md border border-border bg-muted px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" rows={4} placeholder="Answer the questions above" value={answer} onChange={(e) => setAnswer(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), onSubmit(answer))} />
      <button onClick={() => onSubmit(answer)} className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">Send Answers →</button>
    </div>
  );
}
