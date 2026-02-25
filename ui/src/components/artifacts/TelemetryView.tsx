"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SessionSummary } from "@/lib/types";

export function TelemetryView({ sessionId }: { sessionId: string }) {
  const [summary, setSummary] = useState<SessionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    // GET /sessions returns list; fetch the single session summary via list then filter
    api
      .listSessions()
      .then((list) => {
        const s = list.find((x) => x.thread_id === sessionId) ?? null;
        setSummary(s);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) return <p className="text-xs text-muted-foreground">Loading telemetry…</p>;
  if (error) return <p className="text-xs text-destructive">{error}</p>;
  if (!summary) return <p className="text-xs text-muted-foreground">No telemetry available.</p>;

  const phaseDurations = Object.entries(summary.phase_durations_ms ?? {}).sort(
    ([, a], [, b]) => b - a,
  );

  return (
    <div className="space-y-4 text-xs">
      {/* Phase durations */}
      {phaseDurations.length > 0 && (
        <section>
          <p className="mb-1.5 font-medium text-muted-foreground uppercase tracking-wider text-[10px]">
            Phase Durations
          </p>
          <table className="w-full">
            <tbody>
              {phaseDurations.map(([phase, ms]) => (
                <tr key={phase} className="border-b border-border/50 last:border-0">
                  <td className="py-1 pr-2 text-foreground/80 capitalize">{phase}</td>
                  <td className="py-1 text-right tabular-nums text-muted-foreground">
                    {ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* Schema fingerprint + drift */}
      {summary.schema_fingerprint && (
        <section>
          <p className="mb-1 font-medium text-muted-foreground uppercase tracking-wider text-[10px]">
            Schema
          </p>
          <div className="flex items-center gap-2">
            <code className="font-mono text-[10px] text-foreground/70">
              {summary.schema_fingerprint.slice(0, 10)}…
            </code>
            {summary.drift_detected && (
              <span className="rounded bg-amber-600/20 px-1.5 py-0.5 text-[10px] text-amber-400 ring-1 ring-amber-500/30">
                drift
              </span>
            )}
          </div>
        </section>
      )}

      {/* Pattern metrics */}
      {summary.pattern_metrics && (
        <section>
          <p className="mb-1 font-medium text-muted-foreground uppercase tracking-wider text-[10px]">
            Pattern
          </p>
          <div className="space-y-0.5 text-foreground/70">
            {Object.entries(summary.pattern_metrics).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="capitalize">{k.replace(/_/g, " ")}</span>
                <span className="tabular-nums">{String(v)}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Counters */}
      <section>
        <p className="mb-1 font-medium text-muted-foreground uppercase tracking-wider text-[10px]">
          Counters
        </p>
        <div className="space-y-0.5 text-foreground/70">
          <div className="flex justify-between">
            <span>Schema repairs</span>
            <span className="tabular-nums">{summary.knowledge_repair_count}</span>
          </div>
          <div className="flex justify-between">
            <span>Node cache hits</span>
            <span className="tabular-nums">{summary.get_node_calls_total}</span>
          </div>
          <div className="flex justify-between">
            <span>Total repair events</span>
            <span className="tabular-nums">{summary.total_repair_events}</span>
          </div>
        </div>
      </section>
    </div>
  );
}
