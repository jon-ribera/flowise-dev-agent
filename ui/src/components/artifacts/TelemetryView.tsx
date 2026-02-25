"use client";
export function TelemetryView({ sessionId }: { sessionId: string }) {
  // TODO: render phase_durations_ms, schema_fingerprint, drift_detected, pattern_metrics
  return <p className="text-xs text-muted-foreground">TODO: telemetry for {sessionId}</p>;
}
