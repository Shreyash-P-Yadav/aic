/**
 * The typed API client.
 *
 * One place that knows about HTTP. Errors come back as the API's own
 * `ProblemDetail`, so an entitlement denial reaches the UI carrying the contract's
 * policy text verbatim — which is what makes the refusal legible instead of a 403.
 */

import type {
  AskResponse,
  AuditEntry,
  CalibrationResponse,
  DQResponse,
  EvidenceDrawer,
  FreshnessResponse,
  InsightPayload,
  InsightSummary,
  NarrativeResponse,
  ProblemDetail,
  RoleSummary,
  SessionResponse,
  SourceSummary,
  TelemetryResponse,
} from './types';

export class ApiError extends Error {
  constructor(readonly problem: ProblemDetail) {
    super(problem.title);
    this.name = 'ApiError';
  }

  /** The policy text a contract supplied, when there is one. */
  get reason(): string | null {
    return this.problem.reason;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as ProblemDetail | null;
    throw new ApiError(
      problem ?? {
        type: 'HttpError',
        title: `${response.status} ${response.statusText}`,
        status: response.status,
        detail: null,
        reason: null,
      },
    );
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string; version: string; llm_provider: string }>('/api/health'),
  roles: () => request<RoleSummary[]>('/api/session/roles'),
  session: () => request<SessionResponse>('/api/session'),
  setRole: (role: string) =>
    request<SessionResponse>('/api/session/role', {
      method: 'POST',
      body: JSON.stringify({ role }),
    }),
  insights: (params: { status?: string; kpi?: string } = {}) => {
    const pairs = Object.entries(params).flatMap(([key, value]) =>
      value ? [[key, value] as [string, string]] : [],
    );
    const query = new URLSearchParams(pairs).toString();
    return request<InsightSummary[]>(`/api/insights${query ? `?${query}` : ''}`);
  },
  insight: (id: string) => request<InsightPayload>(`/api/insights/${id}`),
  narrative: (id: string, persona: string) =>
    request<NarrativeResponse>(`/api/insights/${id}/narrative?persona=${persona}`),
  evidence: (id: string) => request<EvidenceDrawer>(`/api/insights/${id}/evidence`),
  feedback: (id: string, text: string) =>
    request<{ label: string; reason: string }>(`/api/insights/${id}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  ask: (question: string) =>
    request<AskResponse>('/api/ask', { method: 'POST', body: JSON.stringify({ question }) }),
  sources: () => request<SourceSummary[]>('/api/sources'),
  freshness: () => request<FreshnessResponse[]>('/api/freshness'),
  dq: () => request<DQResponse[]>('/api/dq'),
  telemetry: () => request<TelemetryResponse>('/api/telemetry'),
  calibration: () => request<CalibrationResponse>('/api/calibration'),
  audit: () => request<AuditEntry[]>('/api/audit'),
  demo: (control: 'inject-event' | 'break-feed', target: string) =>
    request<{ control: string; detail: string; sim_time: string }>(`/api/demo/${control}`, {
      method: 'POST',
      body: JSON.stringify({ target }),
    }),
};
