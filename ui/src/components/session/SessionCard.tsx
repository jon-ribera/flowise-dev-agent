"use client";
import { useRouter } from "next/navigation";
import type { SessionSummary } from "@/lib/types";

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  pending_interrupt: { label: "Waiting for you", color: "text-amber-400 bg-amber-400/10" },
  in_progress: { label: "Running", color: "text-blue-400 bg-blue-400/10" },
  completed: { label: "Done", color: "text-green-400 bg-green-400/10" },
  error: { label: "Error", color: "text-red-400 bg-red-400/10" },
};

export function SessionCard({ session }: { session: SessionSummary }) {
  const router = useRouter();
  const s = STATUS_LABELS[session.status] ?? { label: session.status, color: "" };
  return (
    <div role="button" tabIndex={0}
      onClick={() => router.push(`/sessions/${session.thread_id}`)}
      onKeyDown={(e) => e.key === "Enter" && router.push(`/sessions/${session.thread_id}`)}
      className="flex cursor-pointer items-center gap-4 rounded-lg border border-border p-3 hover:bg-muted/40 focus:outline-none focus:ring-2 focus:ring-ring">
      <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${s.color}`}>{s.label}</span>
      <span className="flex-1 truncate text-sm">{session.session_name ?? session.thread_id.slice(0, 8) + "…"}</span>
      {session.chatflow_id && <span className="hidden shrink-0 font-mono text-xs text-muted-foreground md:block">{session.chatflow_id.slice(0, 8)}…</span>}
      <span className="shrink-0 text-xs text-muted-foreground">iter {session.iteration}</span>
      <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">{(session.total_input_tokens + session.total_output_tokens).toLocaleString()} tok</span>
    </div>
  );
}
