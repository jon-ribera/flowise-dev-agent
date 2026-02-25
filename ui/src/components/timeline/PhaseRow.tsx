"use client";
import type { Phase } from "@/lib/types";
import { NodeRow } from "./NodeRow";
export function PhaseRow({ phase }: { phase: Phase }) {
  const hasActive = phase.nodes.some((n) => ["running", "interrupted"].includes(n.status));
  return (
    <div>
      <div className={`flex items-center gap-2 rounded px-2 py-1 text-xs font-medium ${hasActive ? "text-blue-400" : "text-muted-foreground"}`}>{phase.name}</div>
      <div className="ml-3 space-y-0.5">{phase.nodes.map((n) => <NodeRow key={n.name} node={n} />)}</div>
    </div>
  );
}
