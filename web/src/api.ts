import type { AssistantChatResponse, OpsResult, TraceSpan, User, WorkOrder } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function authHeaders(token: string | null): HeadersInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function request<T>(
  path: string,
  token: string | null,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1${path}`, {
    ...options,
    headers: { ...authHeaders(token), ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(
      response.status,
      data.detail || data.error || `请求失败 (${response.status})`,
    );
  }
  return data as T;
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; user: User }>("/auth/login", null, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  me: (token: string) => request<User>("/auth/me", token),
  listOrders: (token: string) => request<WorkOrder[]>("/work-orders", token),
  getOrder: (token: string, id: string) => request<WorkOrder>(`/work-orders/${id}`, token),
  createOrder: (token: string, payload: unknown) =>
    request<WorkOrder>("/work-orders", token, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  diagnose: (token: string, id: string) =>
    request<WorkOrder>(`/work-orders/${id}/diagnose`, token, { method: "POST" }),
  expertConfirm: (token: string, id: string, body: unknown) =>
    request<WorkOrder>(`/work-orders/${id}/expert-confirm`, token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  approveDispatch: (token: string, id: string, body: unknown) =>
    request<WorkOrder>(`/work-orders/${id}/dispatch/approve`, token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reserveParts: (token: string, id: string, body: unknown) =>
    request<WorkOrder>(`/work-orders/${id}/parts/reserve`, token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  startService: (token: string, id: string) =>
    request<WorkOrder>(`/work-orders/${id}/service/start`, token, { method: "POST" }),
  mismatch: (token: string, id: string, body: unknown) =>
    request<WorkOrder>(`/work-orders/${id}/mismatch`, token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  resumeTakeover: (token: string, id: string) =>
    request<WorkOrder>(`/work-orders/${id}/manual-takeover/resume`, token, {
      method: "POST",
    }),
  close: (token: string, id: string, body: unknown) =>
    request<WorkOrder>(`/work-orders/${id}/close`, token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  approveClose: (token: string, id: string, body: unknown) =>
    request<WorkOrder>(`/work-orders/${id}/close/approve`, token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  opsQuery: (token: string, body: unknown) =>
    request<OpsResult>("/operations/query", token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  assistantChat: (token: string, body: unknown) =>
    request<AssistantChatResponse>("/assistant/chat", token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  traces: (token: string, serviceRequestId?: string) =>
    request<TraceSpan[]>(
      `/traces${serviceRequestId ? `?service_request_id=${serviceRequestId}` : ""}`,
      token,
    ),
  tools: (token: string) => request<{ name: string }[]>("/tools", token),
};
