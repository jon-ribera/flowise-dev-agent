"use client";
import { useSessionStore } from "@/store/session-store";
import { ToolCallFeed } from "./ToolCallFeed";

export function StreamingPanel() {
  const active = useSessionStore((s) => s.active);
  const reconnect = active?.reconnectAttempt ?? null;

  return (
    <div className="space-y-4">
      {reconnect !== null && reconnect >= 1 && reconnect <= 3 && (
        <div className="flex animate-pulse items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          Reconnecting… (attempt {reconnect}/3)
        </div>
      )}
      {reconnect !== null && reconnect >= 4 && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          <span>Connection lost</span>
          <button
            onClick={() => window.location.reload()}
            className="rounded bg-red-700 px-2 py-1 text-xs text-white hover:bg-red-600"
          >
            Retry
          </button>
        </div>
      )}
      <p className="text-xs font-medium text-muted-foreground">Running…</p>
      <ToolCallFeed toolCalls={active?.toolCalls ?? []} />
      {active?.tokens && <pre className="overflow-auto rounded-md bg-muted p-3 font-mono text-xs">{active.tokens}</pre>}
    </div>
  );
}
