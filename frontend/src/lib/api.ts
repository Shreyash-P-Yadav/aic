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
  KpiSeries,
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

/**
 * Every request takes the caller's `AbortSignal`. React Query hands one to each
 * `queryFn` and aborts it when the component unmounts or the key changes, so
 * threading it through is what makes navigating away from a slow screen actually
 * stop the work rather than merely stop rendering it.
 */
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
  health: (signal?: AbortSignal) =>
    request<{ status: string; version: string; llm_provider: string }>('/api/health', { signal }),
  roles: (signal?: AbortSignal) => request<RoleSummary[]>('/api/session/roles', { signal }),
  session: (signal?: AbortSignal) => request<SessionResponse>('/api/session', { signal }),
  setRole: (role: string) =>
    request<SessionResponse>('/api/session/role', {
      method: 'POST',
      body: JSON.stringify({ role }),
    }),
  insights: (params: { status?: string; kpi?: string } = {}, signal?: AbortSignal) => {
    const pairs = Object.entries(params).flatMap(([key, value]) =>
      value ? [[key, value] as [string, string]] : [],
    );
    const query = new URLSearchParams(pairs).toString();
    return request<InsightSummary[]>(`/api/insights${query ? `?${query}` : ''}`, { signal });
  },
  insight: (id: string, signal?: AbortSignal) =>
    request<InsightPayload>(`/api/insights/${id}`, { signal }),
  narrative: (id: string, persona: string, signal?: AbortSignal) =>
    request<NarrativeResponse>(`/api/insights/${id}/narrative?persona=${persona}`, { signal }),
  evidence: (id: string, signal?: AbortSignal) =>
    request<EvidenceDrawer>(`/api/insights/${id}/evidence`, { signal }),
  series: (id: string, signal?: AbortSignal) =>
    request<KpiSeries>(`/api/insights/${id}/series`, { signal }),
  feedback: (id: string, text: string) =>
    request<{ label: string; reason: string }>(`/api/insights/${id}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  ask: (question: string) =>
    request<AskResponse>('/api/ask', { method: 'POST', body: JSON.stringify({ question }) }),
  sources: (signal?: AbortSignal) => request<SourceSummary[]>('/api/sources', { signal }),
  freshness: (signal?: AbortSignal) => request<FreshnessResponse[]>('/api/freshness', { signal }),
  dq: (signal?: AbortSignal) => request<DQResponse[]>('/api/dq', { signal }),
  telemetry: (signal?: AbortSignal) => request<TelemetryResponse>('/api/telemetry', { signal }),
  calibration: (signal?: AbortSignal) =>
    request<CalibrationResponse>('/api/calibration', { signal }),
  audit: (signal?: AbortSignal) => request<AuditEntry[]>('/api/audit', { signal }),
  demo: (control: 'inject-event' | 'break-feed' | 'restore-feed', target: string) =>
    request<{ control: string; detail: string; sim_time: string }>(`/api/demo/${control}`, {
      method: 'POST',
      body: JSON.stringify({ target }),
    }),
};
