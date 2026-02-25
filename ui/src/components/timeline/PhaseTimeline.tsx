"use client";
import { useSessionStore } from "@/store/session-store";
import { PhaseRow } from "./PhaseRow";
export function PhaseTimeline() {
  const phases = useSessionStore((s) => s.active?.phases ?? []);
  return <nav aria-label="Phase timeline" className="space-y-1">{phases.map((p) => <PhaseRow key={p.name} phase={p} />)}</nav>;
}
