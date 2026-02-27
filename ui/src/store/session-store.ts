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
  /** Latest plan text received (preserved after interrupt clears so Artifacts panel can display it) */
  latestPlan: string | null;
  /** Latest test results text (preserved after interrupt clears) */
  latestTestResults: string | null;
  /** SSE reconnect state: null=ok, 1-3=retrying, 4=lost */
  reconnectAttempt: number | null;
  /** True between user clicking a HITL button and first SSE event arriving */
  submitting: boolean;
}

interface SessionStore {
  sessions: SessionSummary[];
  loadingSessions: boolean;
  setSessions: (sessions: SessionSummary[]) => void;
  setLoadingSessions: (loading: boolean) => void;
  active: ActiveSession | null;
  initActive: (id: string) => void;
  startSubmitting: () => void;
  applySSEEvent: (event: SSEEvent) => void;
  applyNodeEvent: (event: NodeSSEEvent) => void;
  setReconnectAttempt: (n: number | null) => void;
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
  initActive: (id) => set({ active: { id, status: "streaming", interrupt: null, phases: initPhases(), tokens: "", toolCalls: [], chatflow_id: null, iteration: 0, total_input_tokens: 0, total_output_tokens: 0, lastNodeSeq: 0, errorDetail: null, latestPlan: null, latestTestResults: null, reconnectAttempt: null, submitting: false } }),

  startSubmitting: () => {
    const a = get().active;
    if (a) set({ active: { ...a, submitting: true, status: "streaming", tokens: "", toolCalls: [] } });
  },

  applySSEEvent: (event) => {
    const a = get().active;
    if (!a) return;
    // Clear submitting flag on any incoming event — backend is responding
    if (a.submitting) { set({ active: { ...a, submitting: false } }); }
    // The backend spreads the interrupt payload dict into the SSE event, so the top-level
    // "type" field is the interrupt subtype (e.g. "plan_approval"), not the string "interrupt".
    // We handle all interrupt subtypes here in addition to the canonical SSE types.
    const evType = (event as unknown as Record<string, string>).type;
    switch (evType) {
      case "token": set({ active: { ...a, tokens: a.tokens + (event as { content: string }).content } }); break;
      case "tool_call": set({ active: { ...a, toolCalls: [...a.toolCalls, { name: (event as { name: string }).name, status: "calling" }] } }); break;
      case "tool_result": { const e = event as { name: string; preview: string }; set({ active: { ...a, toolCalls: a.toolCalls.map((tc) => tc.name === e.name ? { ...tc, status: "done", preview: e.preview } : tc) } }); break; }
      case "done": set({ active: { ...a, status: "completed" } }); break;
      case "error": set({ active: { ...a, status: "error", errorDetail: (event as { detail: string }).detail } }); break;
      // Interrupt subtypes — backend sends type: "plan_approval" | "clarification" | etc.
      case "interrupt":      // future-proof: if api.py is fixed to send type: "interrupt"
      case "plan_approval":
      case "clarification":
      case "credential_check":
      case "result_review":
      case "select_target": {
        const pl = event as unknown as InterruptPayload;
        set({ active: {
          ...a,
          status: "pending_interrupt" as const,
          interrupt: pl,
          latestPlan: pl.plan ?? a.latestPlan,
          latestTestResults: pl.test_results ?? a.latestTestResults,
        } });
        break;
      }
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

  setReconnectAttempt: (n) => {
    const a = get().active;
    if (a) set({ active: { ...a, reconnectAttempt: n } });
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
