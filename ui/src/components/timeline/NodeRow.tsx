"use client";
import type { PhaseNode } from "@/lib/types";
const ICONS: Record<string, string> = { pending: "○", running: "◌", completed: "✓", interrupted: "⏸", failed: "✗", skipped: "–" };
const COLORS: Record<string, string> = { pending: "text-muted-foreground", running: "text-blue-400 animate-pulse", completed: "text-green-400", interrupted: "text-amber-400", failed: "text-red-400", skipped: "text-muted-foreground opacity-50" };
export function NodeRow({ node }: { node: PhaseNode }) {
  return (
    <div className={`flex items-center gap-2 px-2 py-0.5 text-xs ${COLORS[node.status] ?? ""}`} title={node.summary}>
      <span aria-hidden>{ICONS[node.status] ?? "?"}</span>
      <span className="truncate">{node.name}</span>
      {node.duration_ms !== undefined && <span className="ml-auto text-muted-foreground">{node.duration_ms}ms</span>}
    </div>
  );
}
