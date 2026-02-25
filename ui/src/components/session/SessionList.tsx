"use client";
import { useEffect } from "react";
import { useSessionStore } from "@/store/session-store";
import { api } from "@/lib/api";
import { SessionCard } from "./SessionCard";
import { NewSessionModal } from "./NewSessionModal";

export function SessionList() {
  const { sessions, setSessions, setLoadingSessions, modalOpen, setModalOpen } = useSessionStore();

  useEffect(() => {
    let timeout: ReturnType<typeof setTimeout>;
    async function load() {
      setLoadingSessions(true);
      try { const data = await api.listSessions({ sort: "desc" }); setSessions(data); }
      catch (e) { console.error("Failed to load sessions", e); }
      finally { setLoadingSessions(false); }
    }
    function scheduleRefresh() {
      const hasActive = sessions.some((s) => s.status === "in_progress");
      if (hasActive) timeout = setTimeout(() => load().then(scheduleRefresh), 5000);
    }
    load().then(scheduleRefresh);
    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Flowise Dev Agent</h1>
        <button onClick={() => setModalOpen(true)} className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">+ New Session</button>
      </div>
      {sessions.length === 0 ? (
        <div className="rounded-lg border border-border p-12 text-center">
          <p className="mb-4 text-muted-foreground">No sessions yet. Start your first co-development session.</p>
          <button onClick={() => setModalOpen(true)} className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">+ New Session</button>
        </div>
      ) : (
        <div className="space-y-1">{sessions.map((s) => <SessionCard key={s.thread_id} session={s} />)}</div>
      )}
      {modalOpen && <NewSessionModal onClose={() => setModalOpen(false)} />}
    </div>
  );
}
