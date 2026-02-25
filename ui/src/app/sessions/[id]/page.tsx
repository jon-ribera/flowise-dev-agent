"use client";
import { use } from "react";

export default function SessionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <div className="flex h-screen flex-col">
      <div className="border-b border-border px-4 py-2 text-sm text-muted-foreground">Session: {id}</div>
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-60 shrink-0 border-r border-border p-4">
          {/* TODO: <PhaseTimeline sessionId={id} /> */}
          <p className="text-xs text-muted-foreground">Phase Timeline</p>
        </aside>
        <main className="flex-1 overflow-auto p-4">
          {/* TODO: <ActivePanel sessionId={id} /> */}
          <p className="text-xs text-muted-foreground">Active Panel</p>
        </main>
        <aside className="w-80 shrink-0 border-l border-border p-4">
          {/* TODO: <ArtifactsPanel sessionId={id} /> */}
          <p className="text-xs text-muted-foreground">Artifacts Panel</p>
        </aside>
      </div>
    </div>
  );
}
