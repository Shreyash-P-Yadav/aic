/**
 * Types mirroring the API's pydantic models.
 *
 * Hand-written rather than generated so the compile error lands on the line that
 * reads the field, not inside a 4,000-line generated file. The API's OpenAPI schema
 * is the contract; these are the half of it this app actually consumes.
 */

export type Tier = 'High' | 'Moderate' | 'Low' | 'Insufficient';
export type InsightStatus = 'published' | 'abstained';
export type FreshnessState = 'green' | 'amber' | 'red' | 'unknown';

export interface RoleSummary {
  name: string;
  display_name: string;
  description: string;
  bindings: Record<string, string>;
}

export interface SessionResponse {
  user_id: string;
  role: string;
  display_name: string;
  run_id: string;
}

export interface InsightSummary {
  insight_id: string;
  kpi_id: string;
  status: InsightStatus;
  tier: Tier;
  delta_pct: number;
  created_at: string;
  headline: string;
}

export interface NumberFact {
  key: string;
  value: number;
  unit: string;
  method: string;
}

export interface SegmentFact {
  label: string;
  actual: number;
  forecast: number;
  explanatory_power: number;
  surprise: number;
  stability: number;
  simpson_flag: boolean;
}

export interface DriverFact {
  driver_id: string;
  coefficient: number;
  interval_low: number;
  interval_high: number;
  p_value: number;
  agreement: number;
  group: string[];
}

export interface EvidenceFact {
  doc_id: string;
  kind: string;
  title: string;
  publish_date: string;
  effective_date: string;
  source_tier: number;
  confidence: number;
  independence_key: string;
  matched_on: string;
}

export interface ActionFact {
  action_id: string;
  driver_id: string;
  lever: string;
  title: string;
  expected_impact_central: number;
  expected_impact_low: number;
  expected_impact_high: number;
  owner_role: string;
  needs_approval: boolean;
  monitoring_kpi: string;
  monitoring_checkpoints: number[];
  success_threshold_pct: number;
  earliest_effect: string;
}

export interface ConfidenceFact {
  signals: Record<string, number>;
  signal_detail: Record<string, string>;
  composite: number;
  calibrated: number;
  calibration_fitted: boolean;
  tier: Tier;
  weakest_signal: string;
  hard_gate_failures: string[];
}

export interface FreshnessFact {
  source_id: string;
  state: FreshnessState;
  age_hours: number | null;
  sla_hours: number;
  latest_period: string | null;
}

export interface LineageStep {
  stage: string;
  frm: string;
  to: string;
  transform: string;
}

export interface InsightBundle {
  insight_id: string;
  kpi_id: string;
  contract_version: string;
  computed_at: string;
  period_start: string;
  period_end: string;
  watermark: string | null;
  observed: number;
  counterfactual: number;
  delta: number;
  delta_pct: number;
  detection_method: string;
  p_value: number;
  numbers: NumberFact[];
  segments: SegmentFact[];
  price_effect: number | null;
  /** Revenue in the window the price-volume-mix split compares AGAINST. */
  pvm_reference: number | null;
  /** Revenue in the window being decomposed. */
  pvm_comparison: number | null;
  /** Which two windows were compared, in words. */
  pvm_label: string;
  volume_effect: number | null;
  mix_effect: number | null;
  drivers: DriverFact[];
  explained_fraction: number;
  unexplained_fraction: number;
  evidence: EvidenceFact[];
  evidence_corroboration: number;
  evidence_rejected_by_timing: string[];
  confidence: ConfidenceFact;
  actions: ActionFact[];
  freshness: FreshnessFact[];
  lineage: LineageStep[];
}

export interface Abstention {
  insight_id: string;
  kpi_id: string;
  computed_at: string;
  period_start: string;
  period_end: string;
  observed_movement: string;
  what_is_known: string[];
  failed_checks: string[];
  missing_evidence: string[];
  retry_trigger: string;
  eta: string | null;
  confidence: ConfidenceFact;
  freshness: FreshnessFact[];
}

export type InsightPayload = InsightBundle | Abstention;

export function isAbstention(payload: InsightPayload): payload is Abstention {
  return 'observed_movement' in payload;
}

export interface NarrativeResponse {
  persona: string;
  tier: Tier;
  text: string;
  source: string;
  attempts: number;
  numbers_checked: number;
  numbers_unsupported: number;
  faithfulness: number;
  cached: boolean;
}

export interface SourceSummary {
  source_id: string;
  system: string;
  owner: string;
  cadence: string;
  format: string;
  quality_tier: string;
  latency_sla_hours: number;
  known_issues: string[];
}

export interface FreshnessResponse extends FreshnessFact {
  detail: string;
}

export interface DQResponse {
  source_id: string;
  expectation: string;
  outcome: string;
  observed: number | null;
  threshold: number | null;
  rows_affected: number;
  detail: string;
}

export interface TelemetryResponse {
  insights_metered: number;
  mean_usd_per_insight: number;
  mean_inr_per_insight: number;
  total_usd: number;
  model_calls: number;
  cache_hits: number;
  downgrades: number;
}

export interface CalibrationResponse {
  fitted: boolean;
  n_points: number;
  detail: string;
}

export interface AuditEntry {
  run_id: string;
  event: string;
  role: string;
  contract_id: string | null;
  outcome: string;
  reason: string | null;
  rows_returned: number | null;
}

export interface AskResponse {
  kind: 'answer' | 'clarification';
  question: string | null;
  insight_id: string | null;
  narrative: string | null;
  detail: string;
}

export interface EvidenceDrawer {
  insight_id: string;
  confidence: ConfidenceFact;
  freshness: FreshnessFact[];
  numbers?: NumberFact[];
  segments?: SegmentFact[];
  drivers?: DriverFact[];
  documents?: EvidenceFact[];
  lineage?: LineageStep[];
  rejected_by_timing?: string[];
  explained_fraction?: number;
  unexplained_fraction?: number;
  what_is_known?: string[];
  failed_checks?: string[];
  missing_evidence?: string[];
  retry_trigger?: string;
}

export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail: string | null;
  reason: string | null;
}
