"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { VersionSnapshot } from "@/lib/types";

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function VersionHistory({ sessionId }: { sessionId: string }) {
  const [versions, setVersions] = useState<VersionSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rollingBack, setRollingBack] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .listVersions(sessionId)
      .then((r) => setVersions(r.versions))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [sessionId]);

  async function handleRollback(label: string) {
    setRollingBack(label);
    try {
      await api.rollback(sessionId, label);
      setToast(`Rolled back to ${label}`);
      setTimeout(() => setToast(null), 3000);
    } catch (e) {
      setToast(`Rollback failed: ${(e as Error).message}`);
      setTimeout(() => setToast(null), 4000);
    } finally {
      setRollingBack(null);
    }
  }

  if (loading) return <p className="text-xs text-muted-foreground">Loading versions…</p>;
  if (error) return <p className="text-xs text-destructive">{error}</p>;
  if (versions.length === 0) return <p className="text-xs text-muted-foreground">No snapshots yet.</p>;

  return (
    <div className="space-y-2">
      {toast && (
        <div className="rounded bg-muted px-3 py-1.5 text-xs text-foreground">{toast}</div>
      )}
      {versions.map((v) => (
        <div
          key={v.version_label}
          className="flex items-start justify-between gap-2 rounded-md border border-border p-2.5"
        >
          <div className="min-w-0 space-y-0.5">
            <p className="text-xs font-medium">{v.version_label}</p>
            {v.chatflow_id && (
              <p className="truncate font-mono text-[10px] text-muted-foreground">{v.chatflow_id}</p>
            )}
            <p className="text-[10px] text-muted-foreground">{relativeTime(v.timestamp)}</p>
          </div>
          <button
            onClick={() => handleRollback(v.version_label)}
            disabled={rollingBack === v.version_label}
            className="shrink-0 rounded border border-border px-2 py-0.5 text-[10px] hover:bg-muted disabled:opacity-50"
          >
            {rollingBack === v.version_label ? "…" : "Rollback"}
          </button>
        </div>
      ))}
    </div>
  );
}
