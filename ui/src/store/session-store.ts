import { create } from "zustand";
import type { SessionSummary, SessionResponse, InterruptPayload, Phase, ToolCall, SSEEvent, NodeSSEEvent } from "@/lib/types";

export const PHASES: { name: string; nodes: string[] }[] = [
  { name: "Classify", nodes: ["classify_intent"] },
  { name: "Hydrate", nodes: ["hydrate_context"] },
  { name: "Resolve", nodes: ["resolve_target", "hitl_select_target"] },
  { name: "Load", nodes: ["load_current_flow", "summarize_current_flow"] },
  { name: "Plan", nodes: ["plan_v2", "hitl_plan_v2"] },
  { name: "Patch", nodes: ["define_patch_scope", "compile_patch_ir", "compile_flow_data", "validate", "repair_schema", "preflight_validate_patch"] },
  { name: "Apply", nodes: ["apply_patch", "test_v2", "evaluate", "hitl_review_v2"] },
];

function initPhases(): Phase[] {
  return PHASES.map((p) => ({ name: p.name, nodes: p.nodes.map((n) => ({ name: n, status: "pending" as const })), expanded: true }));
}

interface ActiveSession {
  id: string;
  status: SessionResponse["status"] | "streaming";
  interrupt: InterruptPayload | null;
  phases: Phase[];
  tokens: string;
  toolCalls: ToolCall[];
  chatflow_id: string | null;
  iteration: number;
  total_input_tokens: number;
  total_output_tokens: number;
  lastNodeSeq: number;
  errorDetail: string | null;
}

interface SessionStore {
  sessions: SessionSummary[];
  loadingSessions: boolean;
  setSessions: (sessions: SessionSummary[]) => void;
  setLoadingSessions: (loading: boolean) => void;
  active: ActiveSession | null;
  initActive: (id: string) => void;
  applySSEEvent: (event: SSEEvent) => void;
  applyNodeEvent: (event: NodeSSEEvent) => void;
  clearActive: () => void;
  modalOpen: boolean;
  setModalOpen: (open: boolean) => void;
  apiKey: string;
  setApiKey: (key: string) => void;
}

export const useSessionStore = create<SessionStore>((set, get) => ({
  sessions: [],
  loadingSessions: false,
  setSessions: (sessions) => set({ sessions }),
  setLoadingSessions: (loading) => set({ loadingSessions: loading }),

  active: null,
  initActive: (id) => set({ active: { id, status: "streaming", interrupt: null, phases: initPhases(), tokens: "", toolCalls: [], chatflow_id: null, iteration: 0, total_input_tokens: 0, total_output_tokens: 0, lastNodeSeq: 0, errorDetail: null } }),

  applySSEEvent: (event) => {
    const a = get().active;
    if (!a) return;
    switch (event.type) {
      case "token": set({ active: { ...a, tokens: a.tokens + event.content } }); break;
      case "tool_call": set({ active: { ...a, toolCalls: [...a.toolCalls, { name: event.name, status: "calling" }] } }); break;
      case "tool_result": set({ active: { ...a, toolCalls: a.toolCalls.map((tc) => tc.name === event.name ? { ...tc, status: "done", preview: event.preview } : tc) } }); break;
      case "interrupt": set({ active: { ...a, status: "pending_interrupt" as const, interrupt: event as InterruptPayload } }); break;
      case "done": set({ active: { ...a, status: "completed" } }); break;
      case "error": set({ active: { ...a, status: "error", errorDetail: event.detail } }); break;
    }
  },

  applyNodeEvent: (event) => {
    const a = get().active;
    if (!a) return;
    if (event.type === "done") {
      set({ active: { ...a, phases: a.phases.map((p) => ({ ...p, nodes: p.nodes.map((n) => n.status === "pending" ? { ...n, status: "skipped" as const } : n) })) } });
      return;
    }
    const seq = "seq" in event ? event.seq : a.lastNodeSeq;
    const phases = a.phases.map((p) => ({
      ...p,
      nodes: p.nodes.map((n) => {
        if (n.name !== event.node_name) return n;
        if (event.type === "node_start") return { ...n, status: "running" as const };
        if (event.type === "node_end") return { ...n, status: "completed" as const, duration_ms: event.duration_ms, summary: event.summary };
        if (event.type === "node_error") return { ...n, status: "failed" as const, duration_ms: event.duration_ms, summary: event.summary };
        if (event.type === "interrupt") return { ...n, status: "interrupted" as const };
        return n;
      }),
    }));
    set({ active: { ...a, phases, lastNodeSeq: seq } });
  },

  clearActive: () => set({ active: null }),
  modalOpen: false,
  setModalOpen: (open) => set({ modalOpen: open }),
  apiKey: typeof window !== "undefined" ? localStorage.getItem("flowise_agent_api_key") ?? "" : "",
  setApiKey: (key) => {
    if (typeof window !== "undefined") { if (key) localStorage.setItem("flowise_agent_api_key", key); else localStorage.removeItem("flowise_agent_api_key"); }
    set({ apiKey: key });
  },
}));
