import type { SSEEvent, NodeSSEEvent } from "./types";

const getApiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const getApiKey = () => typeof window !== "undefined" ? localStorage.getItem("flowise_agent_api_key") ?? "" : "";

async function readSSEStream(body: ReadableStream<Uint8Array>, onEvent: (ev: unknown) => void) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try { onEvent(JSON.parse(line.slice(6))); } catch { /* ignore */ }
      }
    }
  }
}

export function openNewSessionStream(
  body: { requirement: string; thread_id: string; test_trials: number; flowise_instance_id?: string },
  onEvent: (e: SSEEvent) => void,
  onError?: (err: unknown) => void
): () => void {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await fetch(`${getApiUrl()}/sessions/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(getApiKey() ? { Authorization: `Bearer ${getApiKey()}` } : {}) },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) { onError?.(new Error(`HTTP ${res.status}`)); return; }
      await readSSEStream(res.body, onEvent as (e: unknown) => void);
    } catch (e) { if ((e as Error).name !== "AbortError") onError?.(e); }
  })();
  return () => ctrl.abort();
}

export function openResumeStream(
  threadId: string, response: string,
  onEvent: (e: SSEEvent) => void, onError?: (err: unknown) => void
): () => void {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await fetch(`${getApiUrl()}/sessions/${threadId}/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(getApiKey() ? { Authorization: `Bearer ${getApiKey()}` } : {}) },
        body: JSON.stringify({ response }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) { onError?.(new Error(`HTTP ${res.status}`)); return; }
      await readSSEStream(res.body, onEvent as (e: unknown) => void);
    } catch (e) { if ((e as Error).name !== "AbortError") onError?.(e); }
  })();
  return () => ctrl.abort();
}

export function openNodeStream(
  threadId: string, afterSeq: number,
  onEvent: (e: NodeSSEEvent) => void,
  onError?: (err: unknown) => void,
  onReconnecting?: (attempt: number) => void,
): () => void {
  let stopped = false, attempt = 0, lastSeq = afterSeq;
  const connect = () => {
    if (stopped) return;
    (async () => {
      try {
        const res = await fetch(`${getApiUrl()}/sessions/${threadId}/stream?after_seq=${lastSeq}`, {
          headers: getApiKey() ? { Authorization: `Bearer ${getApiKey()}` } : {},
        });
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
        if (attempt > 0) onReconnecting?.(0);  // signal successful reconnect
        attempt = 0;
        await readSSEStream(res.body, (ev) => {
          if (ev && typeof ev === "object" && "seq" in ev) lastSeq = (ev as { seq: number }).seq;
          onEvent(ev as NodeSSEEvent);
          if ((ev as NodeSSEEvent).type === "done") stopped = true;
        });
      } catch (e) {
        if (stopped) return;
        if (attempt < 3) {
          onReconnecting?.(attempt + 1);
          const delay = Math.pow(2, attempt++) * 1000;
          setTimeout(connect, delay);
        } else onError?.(e);
      }
    })();
  };
  connect();
  return () => { stopped = true; };
}
