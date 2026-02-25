"use client";
import { useState } from "react";
import type { Phase } from "@/lib/types";
import { NodeRow } from "./NodeRow";

function phaseIcon(phase: Phase): string {
  if (phase.nodes.some((n) => n.status === "interrupted")) return "⏸";
  if (phase.nodes.some((n) => n.status === "running"))     return "◉";
  if (phase.nodes.some((n) => n.status === "failed"))      return "✗";
  if (phase.nodes.every((n) => n.status === "skipped"))    return "⊘";
  if (phase.nodes.every((n) => ["completed", "skipped"].includes(n.status))) return "●";
  return "○";
}

function phaseColor(phase: Phase): string {
  if (phase.nodes.some((n) => n.status === "interrupted")) return "text-amber-400";
  if (phase.nodes.some((n) => n.status === "running"))     return "text-blue-400";
  if (phase.nodes.some((n) => n.status === "failed"))      return "text-destructive";
  if (phase.nodes.every((n) => n.status === "skipped"))    return "text-muted-foreground/40";
  if (phase.nodes.every((n) => ["completed", "skipped"].includes(n.status))) return "text-green-400";
  return "text-muted-foreground";
}

export function PhaseRow({ phase }: { phase: Phase }) {
  const [expanded, setExpanded] = useState(true);
  const completedCount = phase.nodes.filter((n) => n.status === "completed").length;
  const totalCount = phase.nodes.length;
  const icon  = phaseIcon(phase);
  const color = phaseColor(phase);

  return (
    <div>
      <button
        onClick={() => setExpanded((v) => !v)}
        className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-xs font-medium hover:bg-muted/40 ${color}`}
      >
        <span className="shrink-0 w-3 text-center leading-none">{expanded ? "▾" : "▸"}</span>
        <span className="flex-1 text-left">{phase.name}</span>
        <span className="shrink-0 tabular-nums opacity-60">{icon} {completedCount}/{totalCount}</span>
      </button>
      {expanded && (
        <div className="ml-4 mt-0.5 space-y-0.5 border-l border-border/40 pl-2">
          {phase.nodes.map((n) => <NodeRow key={n.name} node={n} />)}
        </div>
      )}
    </div>
  );
}
