"use client";
import { useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useSessionStore } from "@/store/session-store";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { openNodeStream, openResumeStream } from "@/lib/sse";
import { SessionHeader } from "@/components/session/SessionHeader";
import { PhaseTimeline } from "@/components/timeline/PhaseTimeline";
import { ActivePanel } from "@/components/hitl/ActivePanel";
import { ArtifactsPanel } from "@/components/artifacts/ArtifactsPanel";
import type { SSEEvent } from "@/lib/types";

export default function SessionDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const router = useRouter();
  const { toast } = useToast();
  const { initActive, applySSEEvent, applyNodeEvent, setReconnectAttempt, startSubmitting, active } = useSessionStore((s) => ({
    initActive: s.initActive,
    applySSEEvent: s.applySSEEvent,
    applyNodeEvent: s.applyNodeEvent,
    setReconnectAttempt: s.setReconnectAttempt,
    startSubmitting: s.startSubmitting,
    active: s.active,
  }));

  // Ref to cleanup any active POST SSE (resume) stream
  const resumeCleanupRef = useRef<(() => void) | null>(null);

  // 1. On page load: init store, then try to restore session state from API.
  //    NewSessionModal already opened the POST stream and is feeding applySSEEvent,
  //    so we only need to restore state for sessions loaded from the sidebar.
  useEffect(() => {
    initActive(id);
    api
      .getSession(id)
      .then((session) => {
        // Guard: if a POST stream is already feeding events (status === "streaming"),
        // skip applying the GET response — it may reflect stale mid-checkpoint state.
        // This prevents "Built Successfully" flashing on brand-new sessions.
        const current = useSessionStore.getState().active;
        if (current?.status === "streaming") return;

        if (session.interrupt) {
          // Restore HITL state without overwriting a live stream already in progress
          applySSEEvent({ ...session.interrupt, type: session.interrupt.type } as unknown as SSEEvent);
        } else if (session.status === "completed") {
          applySSEEvent({ type: "done", thread_id: id });
        } else if (session.status === "error") {
          applySSEEvent({ type: "error", detail: session.message ?? "Unknown error" } as SSEEvent);
        }
        // status === "in_progress" means a stream is already active (from NewSessionModal)
      })
      .catch((e: unknown) => {
        const status = (e as { status?: number }).status;
        if (status === 404) {
          // Brand-new session not yet checkpointed — skip toast/redirect if streaming
          const current = useSessionStore.getState().active;
          if (current?.status !== "streaming") {
            toast("Session not found", "error");
            router.push("/");
          }
        } else if (status === 401) {
          toast("API key required — check settings above", "error");
        }
        // else: brand-new session not yet persisted — silently ignore
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // 2. Open node lifecycle SSE for PhaseTimeline (auto-reconnects with banner feedback)
  useEffect(() => {
    const stopNodeStream = openNodeStream(
      id,
      0,
      applyNodeEvent,
      () => setReconnectAttempt(4),
      (attempt) => setReconnectAttempt(attempt === 0 ? null : attempt),
    );
    return stopNodeStream;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // 3. Cleanup resume stream on unmount
  useEffect(() => {
    return () => {
      resumeCleanupRef.current?.();
    };
  }, []);

  // 4. HITL response handler — called by ActivePanel when user submits a response
  const handleSubmit = useCallback(
    (response: string) => {
      // Immediately transition to streaming — disables HITL buttons and shows StreamingPanel
      startSubmitting();
      resumeCleanupRef.current?.(); // cancel any previous resume stream
      resumeCleanupRef.current = openResumeStream(
        id,
        response,
        applySSEEvent,
        (err) => {
          applySSEEvent({ type: "error", detail: String(err) } as SSEEvent);
        },
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [id],
  );

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <SessionHeader sessionId={id} />
      <div className="flex min-h-0 flex-1">
        {/* Left: Phase Timeline */}
        <aside className="w-60 shrink-0 overflow-y-auto border-r border-border p-3">
          <PhaseTimeline />
        </aside>

        {/* Center: Active Panel (streaming / HITL) */}
        <main className="flex-1 overflow-y-auto p-6">
          <ActivePanel onSubmit={handleSubmit} />
        </main>

        {/* Right: Artifacts Panel */}
        <aside className="w-80 shrink-0 overflow-y-auto border-l border-border">
          <ArtifactsPanel
            sessionId={id}
            plan={active?.latestPlan ?? null}
            testResults={active?.latestTestResults ?? null}
          />
        </aside>
      </div>
    </div>
  );
}
