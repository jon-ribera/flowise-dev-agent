"use client";
import { useState } from "react";
import { VersionHistory } from "./VersionHistory";
import { TelemetryView } from "./TelemetryView";
import { PatternsBrowser } from "./PatternsBrowser";
const TABS = ["Plan", "Tests", "Versions", "Telemetry", "Patterns"] as const;
type Tab = (typeof TABS)[number];
export function ArtifactsPanel({ sessionId, plan, testResults }: { sessionId: string; plan: string | null; testResults: string | null }) {
  const [tab, setTab] = useState<Tab>("Plan");
  return (
    <div className="flex h-full flex-col">
      <div className="flex border-b border-border">{TABS.map((t) => <button key={t} onClick={() => setTab(t)} className={`px-3 py-2 text-xs font-medium ${tab === t ? "border-b-2 border-primary text-foreground" : "text-muted-foreground hover:text-foreground"}`}>{t}</button>)}</div>
      <div className="flex-1 overflow-auto p-3">
        {tab === "Plan" && <pre className="font-mono text-xs">{plan ?? "(no plan yet)"}</pre>}
        {tab === "Tests" && <pre className="font-mono text-xs">{testResults ?? "(no test results yet)"}</pre>}
        {tab === "Versions" && <VersionHistory sessionId={sessionId} />}
        {tab === "Telemetry" && <TelemetryView sessionId={sessionId} />}
        {tab === "Patterns" && <PatternsBrowser />}
      </div>
    </div>
  );
}
