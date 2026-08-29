/**
 * The five read-only operational screens.
 *
 * They share a shape — fetch, skeleton, empty state, error state, table — so they are
 * one file with five exports rather than five files with the same file in them. Each
 * is small because the interesting work happened in the pipeline that produced the
 * rows; the screen's job is to make it legible.
 */

import { useQuery } from '@tanstack/react-query';

import {
  Card,
  EmptyState,
  ErrorState,
  FreshnessBadge,
  SectionTitle,
  SimulatedLabel,
  Skeleton,
} from '@/components/primitives';
import { api, ApiError } from '@/lib/api';
import { share } from '@/lib/format';

function Panel<T>({
  title,
  hint,
  query,
  empty,
  children,
}: {
  title: string;
  hint?: string;
  query: { isPending: boolean; isError: boolean; error: unknown; data: T[] | undefined };
  empty: string;
  children: (rows: T[]) => React.ReactNode;
}) {
  return (
    <Card>
      <SectionTitle hint={hint}>{title}</SectionTitle>
      {query.isPending ? <Skeleton rows={3} /> : null}
      {query.isError ? (
        <EmptyState
          title={empty}
          detail={
            query.error instanceof ApiError
              ? (query.error.problem.detail ?? query.error.problem.title)
              : String(query.error)
          }
        />
      ) : null}
      {query.data?.length === 0 ? <EmptyState title={empty} /> : null}
      {query.data && query.data.length > 0 ? children(query.data) : null}
    </Card>
  );
}

export function DataSources() {
  const sources = useQuery({ queryKey: ['sources'], queryFn: api.sources });
  const freshness = useQuery({ queryKey: ['freshness'], queryFn: api.freshness, retry: false });
  const dq = useQuery({ queryKey: ['dq'], queryFn: api.dq, retry: false });
  return (
    <div className="space-y-6">
      <SimulatedLabel />
      <Panel
        title="Source contracts"
        hint="Eleven feeds, each with its own cadence and its own way of being wrong"
        query={sources}
        empty="No source contracts loaded"
      >
        {(rows) => (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((source) => (
              <article key={source.source_id} className="rounded border border-hairline-border p-3">
                <p className="text-sm font-medium text-ink">{source.source_id}</p>
                <p className="mt-0.5 text-xs text-ink-secondary">{source.system}</p>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-ink-muted">
                  <dt>Cadence</dt>
                  <dd className="text-ink-secondary">{source.cadence}</dd>
                  <dt>SLA</dt>
                  <dd className="tnum text-ink-secondary">{source.latency_sla_hours}h</dd>
                  <dt>Quality</dt>
                  <dd className="text-ink-secondary">{source.quality_tier}</dd>
                </dl>
                {source.known_issues.length > 0 ? (
                  <p className="mt-2 text-[11px] text-ink-muted">
                    Known issues: {source.known_issues.join(', ')}
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </Panel>
      <Panel title="Freshness" query={freshness} empty="No warehouse is loaded">
        {(rows) => (
          <ul className="space-y-1 text-sm">
            {rows.map((row) => (
              <li key={row.source_id} className="flex flex-wrap justify-between gap-2">
                <span className="text-ink-secondary">{row.source_id}</span>
                <FreshnessBadge state={row.state} />
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel
        title="Data quality"
        hint="Quarantine, never drop — every held row is countable with a reason"
        query={dq}
        empty="No warehouse is loaded"
      >
        {(rows) => (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] text-xs">
              <thead>
                <tr className="border-b border-hairline-grid text-left text-ink-muted">
                  <th className="py-1.5 pr-3 font-medium">Source</th>
                  <th className="py-1.5 pr-3 font-medium">Expectation</th>
                  <th className="py-1.5 pr-3 font-medium">Outcome</th>
                  <th className="py-1.5 font-medium">Rows</th>
                </tr>
              </thead>
              <tbody className="tnum text-ink-secondary">
                {rows.slice(0, 40).map((row, index) => (
                  <tr key={index} className="border-b border-hairline-grid last:border-0">
                    <td className="py-1.5 pr-3">{row.source_id}</td>
                    <td className="py-1.5 pr-3">{row.expectation}</td>
                    <td className="py-1.5 pr-3">{row.outcome}</td>
                    <td className="py-1.5">{row.rows_affected}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

export function TrustCalibration() {
  const calibration = useQuery({ queryKey: ['calibration'], queryFn: api.calibration });
  return (
    <div className="space-y-6">
      <SimulatedLabel />
      <Card>
        <SectionTitle hint="Confidence is computed and calibrated, never claimed">
          Calibration
        </SectionTitle>
        {calibration.isPending ? <Skeleton rows={2} /> : null}
        {calibration.isError ? <ErrorState title="Could not read the calibration state" /> : null}
        {calibration.data ? (
          <div className="space-y-2">
            <p className="text-2xl font-semibold text-ink">
              {calibration.data.fitted ? 'Fitted' : 'Not yet fitted'}
            </p>
            <p className="text-sm text-ink-secondary">{calibration.data.detail}</p>
            <p className="text-xs text-ink-muted">
              n = {calibration.data.n_points} backtested outcomes. Until the isotonic map is fitted
              the composite score is shown raw and labelled uncalibrated — a fabricated calibration
              curve would be worse than none.
            </p>
          </div>
        ) : null}
      </Card>
    </div>
  );
}

export function Telemetry() {
  const telemetry = useQuery({ queryKey: ['telemetry'], queryFn: api.telemetry });
  return (
    <div className="space-y-6">
      <SimulatedLabel />
      <Card>
        <SectionTitle hint="A measurement, not a claim">Model cost</SectionTitle>
        {telemetry.isPending ? <Skeleton rows={2} /> : null}
        {telemetry.data ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Insights metered" value={String(telemetry.data.insights_metered)} />
            <Stat
              label="Mean cost / insight"
              value={`₹${telemetry.data.mean_inr_per_insight.toFixed(3)}`}
            />
            <Stat label="Model calls" value={String(telemetry.data.model_calls)} />
            <Stat
              label="Cache hit rate"
              value={
                telemetry.data.model_calls + telemetry.data.cache_hits === 0
                  ? '—'
                  : share(
                      telemetry.data.cache_hits /
                        (telemetry.data.model_calls + telemetry.data.cache_hits),
                    )
              }
            />
          </div>
        ) : null}
        <p className="mt-3 text-xs text-ink-muted">
          {telemetry.data?.downgrades ?? 0} call(s) downshifted to a smaller model by the
          per-insight cost cap. A downgrade is always logged, so a cheaper narrative is never
          mistaken for a considered one.
        </p>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
    </div>
  );
}

export function Audit() {
  const audit = useQuery({ queryKey: ['audit'], queryFn: api.audit });
  return (
    <div className="space-y-6">
      <SimulatedLabel />
      <Panel
        title="Audit log"
        hint="A refusal is as auditable as a result"
        query={audit}
        empty="Nothing audited yet in this session"
      >
        {(rows) => (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[38rem] text-xs">
              <thead>
                <tr className="border-b border-hairline-grid text-left text-ink-muted">
                  <th className="py-1.5 pr-3 font-medium">Run</th>
                  <th className="py-1.5 pr-3 font-medium">Event</th>
                  <th className="py-1.5 pr-3 font-medium">Role</th>
                  <th className="py-1.5 pr-3 font-medium">Contract</th>
                  <th className="py-1.5 pr-3 font-medium">Outcome</th>
                  <th className="py-1.5 font-medium">Rows</th>
                </tr>
              </thead>
              <tbody className="tnum text-ink-secondary">
                {rows.map((row, index) => (
                  <tr key={index} className="border-b border-hairline-grid last:border-0">
                    <td className="py-1.5 pr-3">{row.run_id.slice(0, 8)}</td>
                    <td className="py-1.5 pr-3">{row.event}</td>
                    <td className="py-1.5 pr-3">{row.role}</td>
                    <td className="py-1.5 pr-3">{row.contract_id ?? '—'}</td>
                    <td className="py-1.5 pr-3">{row.outcome}</td>
                    <td className="py-1.5">{row.rows_returned ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
