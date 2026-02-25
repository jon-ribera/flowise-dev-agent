"use client";
import { useState } from "react";
import type { InterruptPayload } from "@/lib/types";
function parseTestBadges(r: string | null) {
  if (!r) return { happy: "?", edge: "?" };
  return { happy: /HAPPY PATH \[(PASS|FAIL)\]/i.exec(r)?.[1] ?? "?", edge: /EDGE CASE \[(PASS|FAIL)\]/i.exec(r)?.[1] ?? "?" };
}
export function ResultReview({ interrupt, onSubmit }: { interrupt: InterruptPayload; onSubmit: (r: string) => void }) {
  const [feedback, setFeedback] = useState("");
  const [show, setShow] = useState(false);
  const badges = parseTestBadges(interrupt.test_results);
  const badgeColor = (v: string) => v === "PASS" ? "bg-green-400/10 text-green-400" : "bg-red-400/10 text-red-400";
  return (
    <div className="space-y-4">
      <p className="text-sm font-medium text-blue-400">✓ Tests Complete — Review Results</p>
      <div className="flex gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${badgeColor(badges.happy)}`}>HAPPY PATH [{badges.happy}]</span>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${badgeColor(badges.edge)}`}>EDGE CASE [{badges.edge}]</span>
      </div>
      <button onClick={() => setShow(!show)} className="text-xs text-muted-foreground hover:text-foreground">{show ? "▲ Hide details" : "▼ Show details"}</button>
      {show && <pre className="overflow-auto rounded-md bg-muted p-3 font-mono text-xs">{interrupt.test_results}</pre>}
      <textarea autoFocus className="w-full resize-none rounded-md border border-border bg-muted px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" rows={2} placeholder="Describe what to change…" value={feedback} onChange={(e) => setFeedback(e.target.value)} />
      <div className="flex gap-2">
        <button onClick={() => onSubmit("accepted")} className="rounded bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-500">✓ Accept &amp; Done</button>
        {feedback && <button onClick={() => onSubmit(feedback)} className="rounded border border-border px-4 py-2 text-sm hover:bg-muted">Request Changes →</button>}
        <button onClick={() => onSubmit("rollback")} className="rounded border border-red-600/50 px-4 py-2 text-sm text-red-400 hover:bg-red-600/10">↩ Rollback</button>
      </div>
    </div>
  );
}
