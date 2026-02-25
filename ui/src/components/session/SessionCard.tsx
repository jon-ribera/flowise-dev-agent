"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Pencil, MoreHorizontal } from "lucide-react";
import type { SessionSummary } from "@/lib/types";
import { api } from "@/lib/api";
import { useSessionStore } from "@/store/session-store";
import { useToast } from "@/components/ui/Toast";

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  pending_interrupt: { label: "Waiting for you", color: "text-amber-400 bg-amber-400/10" },
  in_progress:       { label: "Running",         color: "text-blue-400 bg-blue-400/10" },
  completed:         { label: "Done",             color: "text-green-400 bg-green-400/10" },
  error:             { label: "Error",            color: "text-red-400 bg-red-400/10" },
};

export function SessionCard({ session }: { session: SessionSummary }) {
  const router = useRouter();
  const { sessions, setSessions } = useSessionStore((s) => ({ sessions: s.sessions, setSessions: s.setSessions }));
  const { toast } = useToast();

  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);

  const s = STATUS_LABELS[session.status] ?? { label: session.status, color: "" };
  const displayName = session.session_name ?? session.thread_id.slice(0, 8) + "…";

  function startEdit(e: React.MouseEvent) {
    e.stopPropagation();
    setDraftName(session.session_name ?? "");
    setEditing(true);
  }

  async function commitRename() {
    if (!draftName.trim() || draftName === session.session_name) { setEditing(false); return; }
    setSaving(true);
    try {
      await api.renameSession(session.thread_id, draftName.trim());
      setSessions(sessions.map((ss) => ss.thread_id === session.thread_id ? { ...ss, session_name: draftName.trim() } : ss));
    } catch (e) {
      toast(`Rename failed: ${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  async function handleDelete(e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await api.deleteSession(session.thread_id);
      setSessions(sessions.filter((ss) => ss.thread_id !== session.thread_id));
    } catch (e) {
      toast(`Delete failed: ${(e as Error).message}`, "error");
    } finally {
      setConfirming(false);
    }
  }

  if (confirming) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-red-700/50 bg-red-900/10 p-3 text-xs">
        <span className="flex-1 text-red-300">Delete this session?</span>
        <button onClick={() => setConfirming(false)} className="rounded px-2 py-1 hover:bg-muted">Cancel</button>
        <button onClick={handleDelete} className="rounded bg-red-700 px-2 py-1 text-white hover:bg-red-600">Delete</button>
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => !editing && router.push(`/sessions/${session.thread_id}`)}
      onKeyDown={(e) => e.key === "Enter" && !editing && router.push(`/sessions/${session.thread_id}`)}
      className="group flex cursor-pointer items-center gap-3 rounded-lg border border-border p-3 hover:bg-muted/40 focus:outline-none focus:ring-2 focus:ring-ring"
    >
      {/* Status badge */}
      <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${s.color}`}>{s.label}</span>

      {/* Name / rename input */}
      <div className="flex min-w-0 flex-1 items-center gap-1" onClick={(e) => editing && e.stopPropagation()}>
        {editing ? (
          <input
            autoFocus
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); commitRename(); }
              if (e.key === "Escape") setEditing(false);
            }}
            onBlur={commitRename}
            disabled={saving}
            className="w-full rounded border border-ring bg-muted px-2 py-0.5 text-sm focus:outline-none"
          />
        ) : (
          <>
            <span className="truncate text-sm">{displayName}</span>
            <button
              onClick={startEdit}
              className="shrink-0 opacity-0 transition-opacity group-hover:opacity-60 hover:!opacity-100"
              title="Rename"
            >
              <Pencil size={11} />
            </button>
          </>
        )}
      </div>

      {/* Metadata */}
      {session.chatflow_id && (
        <span className="hidden shrink-0 font-mono text-xs text-muted-foreground md:block">
          {session.chatflow_id.slice(0, 8)}…
        </span>
      )}
      <span className="shrink-0 text-xs text-muted-foreground">iter {session.iteration}</span>
      <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">
        {(session.total_input_tokens + session.total_output_tokens).toLocaleString()} tok
      </span>

      {/* Actions */}
      <button
        onClick={(e) => { e.stopPropagation(); setConfirming(true); }}
        className="shrink-0 opacity-0 transition-opacity group-hover:opacity-60 hover:!opacity-100"
        title="Delete session"
      >
        <MoreHorizontal size={14} />
      </button>
    </div>
  );
}
