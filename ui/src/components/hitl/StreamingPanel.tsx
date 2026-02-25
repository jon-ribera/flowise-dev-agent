"use client";
import { useSessionStore } from "@/store/session-store";
import { ToolCallFeed } from "./ToolCallFeed";
export function StreamingPanel() {
  const active = useSessionStore((s) => s.active);
  return (
    <div className="space-y-4">
      <p className="text-xs font-medium text-muted-foreground">Running…</p>
      <ToolCallFeed toolCalls={active?.toolCalls ?? []} />
      {active?.tokens && <pre className="overflow-auto rounded-md bg-muted p-3 font-mono text-xs">{active.tokens}</pre>}
    </div>
  );
}
