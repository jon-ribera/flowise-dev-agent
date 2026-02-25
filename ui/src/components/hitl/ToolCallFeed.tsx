import type { ToolCall } from "@/lib/types";
export function ToolCallFeed({ toolCalls }: { toolCalls: ToolCall[] }) {
  if (!toolCalls.length) return null;
  return (
    <div className="space-y-1">
      {toolCalls.map((tc, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <span className={tc.status === "done" ? "text-green-400" : "text-blue-400 animate-pulse"}>{tc.status === "done" ? "✓" : "…"}</span>
          <span className="font-mono">{tc.name}</span>
          {tc.preview && <span className="truncate text-muted-foreground">{tc.preview}</span>}
        </div>
      ))}
    </div>
  );
}
