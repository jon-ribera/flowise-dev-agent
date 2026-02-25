"use client";
import type { PhaseNode } from "@/lib/types";

const STATUS_ICON: Record<string, string> = {
  pending:     "○",
  running:     "◉",
  completed:   "●",
  interrupted: "⏸",
  failed:      "✗",
  skipped:     "⊘",
};

const STATUS_COLOR: Record<string, string> = {
  pending:     "text-muted-foreground/50",
  running:     "text-blue-400",
  completed:   "text-green-400",
  interrupted: "text-amber-400",
  failed:      "text-destructive",
  skipped:     "text-muted-foreground/30",
};

function formatDuration(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

export function NodeRow({ node }: { node: PhaseNode }) {
  const icon  = STATUS_ICON[node.status]  ?? "?";
  const color = STATUS_COLOR[node.status] ?? "";
  const isInterrupted = node.status === "interrupted";
  const isRunning     = node.status === "running";

  return (
    <div
      title={node.summary}
      className={[
        "flex items-center gap-1.5 rounded px-2 py-0.5 text-xs",
        color,
        isInterrupted ? "ring-1 ring-amber-500/40 bg-amber-500/5" : "",
      ].join(" ")}
    >
      <span
        aria-hidden
        className={[
          "shrink-0 w-3 text-center leading-none",
          isRunning || isInterrupted ? "animate-pulse" : "",
        ].join(" ")}
      >
        {icon}
      </span>
      <span className={`truncate ${node.status === "skipped" ? "line-through" : ""}`}>
        {node.name}
      </span>
      {node.duration_ms !== undefined && node.duration_ms > 0 && (
        <span className="ml-auto shrink-0 tabular-nums text-muted-foreground/60">
          {formatDuration(node.duration_ms)}
        </span>
      )}
    </div>
  );
}
