export type SessionStatus = "pending_interrupt" | "completed" | "in_progress" | "error";
export type InterruptType = "clarification" | "credential_check" | "plan_approval" | "result_review" | "select_target";
export type NodeStatus = "pending" | "running" | "completed" | "interrupted" | "failed" | "skipped";

export interface SessionSummary {
  thread_id: string;
  status: SessionStatus;
  iteration: number;
  chatflow_id: string | null;
  total_input_tokens: number;
  total_output_tokens: number;
  session_name: string | null;
  runtime_mode: "capability_first" | "compat_legacy" | null;
  total_repair_events: number;
  total_phases_timed: number;
  knowledge_repair_count: number;
  get_node_calls_total: number;
  phase_durations_ms: Record<string, number>;
  schema_fingerprint: string | null;
  drift_detected: boolean;
  pattern_metrics: Record<string, unknown> | null;
  updated_at: string | null;
}

export interface TopMatch { id: string; name: string; updated_at: string; }

export interface InterruptPayload {
  type: InterruptType;
  prompt: string;
  plan: string | null;
  test_results: string | null;
  chatflow_id: string | null;
  iteration: number;
  options: string[] | null;
  missing_credentials: string[] | null;
  top_matches?: TopMatch[];
  pattern_used?: boolean;
  pattern_id?: number | null;
}

export interface SessionResponse {
  thread_id: string;
  status: "pending_interrupt" | "completed" | "error";
  iteration: number;
  chatflow_id: string | null;
  interrupt: InterruptPayload | null;
  message: string | null;
  total_input_tokens: number;
  total_output_tokens: number;
}

export interface VersionSnapshot { version_label: string; chatflow_id: string; timestamp: string; name?: string; }
export interface PatternSummary { id: number; name: string; description?: string; tags: string[]; success_count: number; category?: string; }

export interface TokenEvent { type: "token"; content: string; }
export interface ToolCallEvent { type: "tool_call"; name: string; }
export interface ToolResultEvent { type: "tool_result"; name: string; preview: string; }
export interface InterruptEvent extends InterruptPayload { type: "interrupt"; }
export interface DoneEvent { type: "done"; thread_id: string; }
export interface ErrorEvent { type: "error"; detail: string; }
export type SSEEvent = TokenEvent | ToolCallEvent | ToolResultEvent | InterruptEvent | DoneEvent | ErrorEvent;

export interface NodeStartEvent { type: "node_start"; node_name: string; phase: string; status: "started"; seq: number; }
export interface NodeEndEvent { type: "node_end"; node_name: string; phase: string; status: "completed"; duration_ms: number; summary: string; seq: number; }
export interface NodeErrorEvent { type: "node_error"; node_name: string; phase: string; status: "failed"; duration_ms: number; summary: string; seq: number; }
export interface NodeInterruptEvent { type: "interrupt"; node_name: string; phase: string; status: "interrupted"; seq: number; }
export interface NodeDoneEvent { type: "done"; session_id: string; }
export type NodeSSEEvent = NodeStartEvent | NodeEndEvent | NodeErrorEvent | NodeInterruptEvent | NodeDoneEvent;

export interface PhaseNode { name: string; status: NodeStatus; duration_ms?: number; summary?: string; }
export interface Phase { name: string; nodes: PhaseNode[]; expanded: boolean; }
export interface ToolCall { name: string; status: "calling" | "done"; preview?: string; }
