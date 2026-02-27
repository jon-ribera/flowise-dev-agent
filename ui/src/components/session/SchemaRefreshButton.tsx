"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import type { SchemaStats } from "@/lib/types";

type RefreshState = "idle" | "refreshing" | "done" | "error";

export function SchemaRefreshButton() {
  const { toast } = useToast();
  const [state, setState] = useState<RefreshState>("idle");
  const [stats, setStats] = useState<SchemaStats | null>(null);
  const [showStats, setShowStats] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout>>();

  const loadStats = useCallback(async () => {
    try {
      const s = await api.getSchemaStats();
      setStats(s);
    } catch {
      /* stats are optional — don't block on failure */
    }
  }, []);

  useEffect(() => {
    loadStats();
    return () => { if (pollRef.current) clearTimeout(pollRef.current); };
  }, [loadStats]);

  const startRefresh = useCallback(async () => {
    setState("refreshing");
    try {
      const res = await api.startSchemaRefresh("all", false);
      if (res.status === "already_running") {
        toast("Schema refresh already running", "info");
        setState("idle");
        return;
      }

      // Poll until complete
      const jobId = res.job_id;
      const poll = async () => {
        try {
          const job = await api.getSchemaRefreshStatus(jobId);
          if (job.status === "success") {
            setState("done");
            toast("Schema refresh complete", "success");
            loadStats();
            setTimeout(() => setState("idle"), 2000);
          } else if (job.status === "failed") {
            setState("error");
            toast("Schema refresh failed", "error");
            setTimeout(() => setState("idle"), 3000);
          } else {
            pollRef.current = setTimeout(poll, 2000);
          }
        } catch {
          setState("error");
          toast("Failed to check refresh status", "error");
          setTimeout(() => setState("idle"), 3000);
        }
      };
      pollRef.current = setTimeout(poll, 2000);
    } catch (e) {
      setState("error");
      toast(e instanceof Error ? e.message : "Schema refresh failed", "error");
      setTimeout(() => setState("idle"), 3000);
    }
  }, [toast, loadStats]);

  const label = {
    idle: "Refresh Schemas",
    refreshing: "Refreshing\u2026",
    done: "Done",
    error: "Failed",
  }[state];

  return (
    <div className="relative">
      <div className="flex items-center gap-1.5">
        <button
          onClick={startRefresh}
          disabled={state === "refreshing"}
          className={`rounded border px-3 py-1.5 text-xs font-medium transition-colors ${
            state === "refreshing"
              ? "cursor-wait border-border bg-muted text-muted-foreground"
              : state === "done"
              ? "border-green-700 bg-green-900/40 text-green-300"
              : state === "error"
              ? "border-red-700 bg-red-900/40 text-red-300"
              : "border-border bg-muted text-foreground hover:bg-muted/80"
          }`}
        >
          {state === "refreshing" && (
            <span className="mr-1.5 inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent align-text-bottom" />
          )}
          {label}
        </button>
        {stats && (
          <button
            onClick={() => setShowStats((v) => !v)}
            className="rounded border border-border px-1.5 py-1.5 text-[10px] text-muted-foreground hover:text-foreground"
            title="Schema cache stats"
          >
            {stats.node}n
          </button>
        )}
      </div>

      {showStats && stats && (
        <div className="absolute right-0 top-full z-30 mt-1 w-52 rounded-lg border border-border bg-card p-3 text-xs shadow-lg">
          <p className="mb-2 font-medium text-foreground">Schema Cache</p>
          <div className="space-y-1 text-muted-foreground">
            <div className="flex justify-between">
              <span>Nodes</span>
              <span className="tabular-nums text-foreground">{stats.node}</span>
            </div>
            <div className="flex justify-between">
              <span>Credentials</span>
              <span className="tabular-nums text-foreground">{stats.credential}</span>
            </div>
            <div className="flex justify-between">
              <span>Templates</span>
              <span className="tabular-nums text-foreground">{stats.template}</span>
            </div>
            {stats.stale_count > 0 && (
              <div className="flex justify-between text-yellow-400">
                <span>Stale</span>
                <span className="tabular-nums">{stats.stale_count}</span>
              </div>
            )}
            {stats.last_refresh && (
              <div className="mt-1.5 border-t border-border pt-1.5 text-[10px] text-muted-foreground">
                Last refresh: {new Date(stats.last_refresh).toLocaleString()}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
