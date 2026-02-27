const getApiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const getHeaders = (): HeadersInit => {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const key = typeof window !== "undefined" ? localStorage.getItem("flowise_agent_api_key") : null;
  if (key) headers["Authorization"] = `Bearer ${key}`;
  return headers;
};

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getApiUrl()}${path}`, { ...init, headers: { ...getHeaders(), ...(init?.headers ?? {}) } });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw Object.assign(new Error(detail.detail ?? res.statusText), { status: res.status });
  }
  return res.json() as Promise<T>;
}

import type { SessionSummary, SessionResponse, VersionSnapshot, PatternSummary, SchemaRefreshResponse, SchemaStats } from "./types";

export const api = {
  listSessions: (params?: { sort?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.sort) q.set("sort", params.sort);
    if (params?.limit) q.set("limit", String(params.limit));
    return apiFetch<SessionSummary[]>(`/sessions${q.toString() ? `?${q}` : ""}`);
  },
  getSession: (id: string) => apiFetch<SessionResponse>(`/sessions/${id}`),
  deleteSession: (id: string) => apiFetch<{ deleted: boolean; thread_id: string }>(`/sessions/${id}`, { method: "DELETE" }),
  renameSession: (id: string, name: string) => apiFetch<{ thread_id: string; session_name: string }>(`/sessions/${id}/name`, { method: "PATCH", body: JSON.stringify({ name }) }),
  getSessionSummary: (id: string) => apiFetch<{ thread_id: string; summary: string }>(`/sessions/${id}/summary`),
  listVersions: (id: string) => apiFetch<{ thread_id: string; versions: VersionSnapshot[]; count: number }>(`/sessions/${id}/versions`),
  rollback: (id: string, version?: string) => apiFetch<SessionResponse>(`/sessions/${id}/rollback${version ? `?version=${encodeURIComponent(version)}` : ""}`, { method: "POST" }),
  listPatterns: (q?: string) => apiFetch<PatternSummary[]>(`/patterns${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  listInstances: () => apiFetch<{ default: string | null; instances: string[] }>("/instances"),
  health: () => apiFetch<{ api: string; flowise: string }>("/health"),
  startSchemaRefresh: (scope: string = "all", force: boolean = false) =>
    apiFetch<SchemaRefreshResponse>("/platform/schema/refresh", { method: "POST", body: JSON.stringify({ scope, force }) }),
  getSchemaRefreshStatus: (jobId: string) =>
    apiFetch<{ job_id: string; status: string; summary_json: Record<string, unknown> }>(`/platform/schema/refresh/${jobId}`),
  getSchemaStats: () => apiFetch<SchemaStats>("/platform/schema/stats"),
};
