"use client";
import { useSessionStore } from "@/store/session-store";
import type { Phase } from "@/lib/types";

/** Infer CREATE/UPDATE from which phases have received events */
function detectMode(phases: Phase[]): "CREATE" | "UPDATE" | null {
  const updateNodes = phases
    .filter((p) => p.name === "Resolve" || p.name === "Load")
    .flatMap((p) => p.nodes);
  if (updateNodes.some((n) => ["running", "completed", "interrupted"].includes(n.status))) return "UPDATE";
  if (updateNodes.length > 0 && updateNodes.every((n) => n.status === "skipped")) return "CREATE";
  return null;
}

const STATUS_CONFIG: Record<string, { label: string; cls: string }> = {
  streaming:         { label: "Running",        cls: "bg-blue-600/20 text-blue-400 ring-1 ring-blue-500/30" },
  in_progress:       { label: "Running",        cls: "bg-blue-600/20 text-blue-400 ring-1 ring-blue-500/30" },
  pending_interrupt: { label: "Waiting for you",cls: "bg-amber-600/20 text-amber-400 ring-1 ring-amber-500/30" },
  completed:         { label: "Done",           cls: "bg-green-600/20 text-green-400 ring-1 ring-green-500/30" },
  error:             { label: "Error",          cls: "bg-red-600/20 text-red-400 ring-1 ring-red-500/30" },
};

export function SessionHeader({ sessionId }: { sessionId: string }) {
  const { active, sessions } = useSessionStore((s) => ({ active: s.active, sessions: s.sessions }));
  const summary = sessions.find((s) => s.thread_id === sessionId);

  const name = summary?.session_name ?? `Session ${sessionId.slice(0, 8)}…`;
  const status = active?.status ?? summary?.status ?? "in_progress";
  const mode = active ? detectMode(active.phases) : null;
  const tokens = active
    ? active.total_input_tokens + active.total_output_tokens
    : summary
    ? summary.total_input_tokens + summary.total_output_tokens
    : 0;

  const { label: statusLabel, cls: statusCls } =
    STATUS_CONFIG[status] ?? { label: status, cls: "bg-muted text-muted-foreground" };

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
      <span className="max-w-[260px] truncate text-sm font-medium">{name}</span>
      <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${statusCls}`}>
        {statusLabel}
      </span>
      {mode && (
        <span
          className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${
            mode === "UPDATE"
              ? "bg-purple-600/20 text-purple-400"
              : "bg-indigo-600/20 text-indigo-400"
          }`}
        >
          {mode}
        </span>
      )}
      <div className="flex-1" />
      {tokens > 0 && (
        <span className="text-xs tabular-nums text-muted-foreground">
          {tokens.toLocaleString()} tokens
        </span>
      )}
    </header>
  );
}
